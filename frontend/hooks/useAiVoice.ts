"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import {
  detectSpeechLocaleFromText,
  getStoredTtsEnabled,
  isSpeechSynthesisSupported,
  setStoredTtsEnabled,
  speakText,
  type SpeechLocale,
  type TtsHandle,
} from "@/lib/speech";

/**
 * Hlas v AI asistentovi (beze změny chování z původní stránky): diktování (STT, Ctrl+Shift+M,
 * volitelné automatické odeslání) a předčítání odpovědí (TTS). Roadmap 4C jen přesunul logiku z page.tsx.
 */
export function useAiVoice({
  onDictated,
  onAutoSend,
}: {
  /** Přidá nadiktovaný text do pole pro zprávu. */
  onDictated: (text: string) => void;
  /** Automatické odeslání po diktování (nastaví text a odešle). */
  onAutoSend: (text: string) => void;
}) {
  const [ttsEnabled, setTtsEnabledState] = useState<boolean>(() => getStoredTtsEnabled(true));
  const [activeTtsKey, setActiveTtsKey] = useState<string | null>(null);
  const [isClient, setIsClient] = useState(false);
  const ttsRef = useRef<TtsHandle | null>(null);
  const autoSendRef = useRef(false);
  const callbacks = useRef({ onDictated, onAutoSend });

  useEffect(() => {
    callbacks.current = { onDictated, onAutoSend };
  });

  useEffect(() => {
    queueMicrotask(() => setIsClient(true));
  }, []);

  const stopTts = useCallback(() => {
    ttsRef.current?.stop();
    ttsRef.current = null;
    setActiveTtsKey(null);
  }, []);

  const setTtsEnabled = useCallback(
    (value: boolean) => {
      setTtsEnabledState(value);
      setStoredTtsEnabled(value);
      if (!value) stopTts();
    },
    [stopTts],
  );

  const playText = useCallback(
    (key: string, text: string, preferredLocale: SpeechLocale) => {
      stopTts();
      if (!text || !ttsEnabled || !isSpeechSynthesisSupported()) return;
      const handle = speakText(text, detectSpeechLocaleFromText(text) || preferredLocale);
      ttsRef.current = handle;
      setActiveTtsKey(key);
      const check = window.setInterval(() => {
        if (!handle.isSpeaking()) {
          window.clearInterval(check);
          if (ttsRef.current === handle) {
            ttsRef.current = null;
            setActiveTtsKey((cur) => (cur === key ? null : cur));
          }
        }
      }, 200);
    },
    [stopTts, ttsEnabled],
  );

  const onFinalTranscript = useCallback((text: string) => {
    if (!text) return;
    if (autoSendRef.current) callbacks.current.onAutoSend(text);
    else callbacks.current.onDictated(text);
  }, []);

  const speech = useSpeechRecognition({ onFinalTranscript });

  useEffect(() => {
    autoSendRef.current = speech.autoSend;
  }, [speech.autoSend]);

  const listening = speech.status === "listening" || speech.status === "processing";
  const toggleListening = useCallback(() => {
    if (listening) speech.stop();
    else if (speech.supported) speech.start();
  }, [listening, speech]);

  // Ctrl+Shift+M = hlasové zadávání (jako dřív)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.shiftKey && (e.key === "M" || e.key === "m")) {
        e.preventDefault();
        toggleListening();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleListening]);

  // úklid při odchodu ze stránky
  const stopSpeech = speech.stop;
  useEffect(
    () => () => {
      try {
        stopSpeech();
      } catch {
        /* ignore */
      }
      try {
        stopTts();
      } catch {
        /* ignore */
      }
    },
    [stopSpeech, stopTts],
  );

  return {
    stt: { ...speech, supported: isClient && speech.supported, listening, toggle: toggleListening },
    tts: { supported: isClient && isSpeechSynthesisSupported(), enabled: ttsEnabled, setEnabled: setTtsEnabled, activeKey: activeTtsKey, play: playText, stop: stopTts },
  };
}

export type AiVoice = ReturnType<typeof useAiVoice>;
