"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SpeechLocale, RecorderStatus } from "@/lib/speech";
import {
  DEFAULT_LOCALE,
  getStoredAutoSend,
  getStoredLocale,
  isSpeechRecognitionSupported,
  setStoredAutoSend,
  setStoredLocale,
} from "@/lib/speech";

const DEBUG =
  typeof process !== "undefined" && process.env?.NODE_ENV !== "production";

function logDebug(msg: string, extra?: unknown) {
  if (!DEBUG) return;
  if (extra !== undefined) {
    console.debug(`[SpeechRec] ${msg}`, extra);
  } else {
    console.debug(`[SpeechRec] ${msg}`);
  }
}

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onresult:
    | ((ev: {
        resultIndex: number;
        results: Array<
          Array<{ transcript: string; confidence?: number }> & { isFinal: boolean }
        >;
      }) => void)
    | null;
  onerror: ((ev: { error: string; message?: string }) => void) | null;
  onend: (() => void) | null;
  onspeechend: (() => void) | null;
  onsoundend: (() => void) | null;
  onaudioend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

function tryGetConstructor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  if (typeof w.SpeechRecognition === "function") return w.SpeechRecognition;
  if (typeof w.webkitSpeechRecognition === "function") return w.webkitSpeechRecognition;
  return null;
}

export type UseSpeechRecognitionResult = {
  supported: boolean;
  status: RecorderStatus;
  transcript: string;
  interim: string;
  error: string | null;
  locale: SpeechLocale;
  autoSend: boolean;
  setLocale: (locale: SpeechLocale) => void;
  setAutoSend: (value: boolean) => void;
  start: () => void;
  stop: () => void;
  resetTranscript: () => void;
  consumeFinalTranscript: () => string;
};

export function useSpeechRecognition(options?: {
  onFinalTranscript?: (text: string) => void;
}): UseSpeechRecognitionResult {
  const onFinalRef = useRef<((text: string) => void) | undefined>(undefined);
  useEffect(() => {
    onFinalRef.current = options?.onFinalTranscript;
  }, [options?.onFinalTranscript]);

  const [supported, setSupported] = useState<boolean>(false);
  useEffect(() => {
    queueMicrotask(() => {
      setSupported(isSpeechRecognitionSupported());
    });
  }, []);

  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [locale, setLocaleState] = useState<SpeechLocale>(() => getStoredLocale(DEFAULT_LOCALE));
  const [autoSend, setAutoSendState] = useState<boolean>(() => getStoredAutoSend(false));

  const recogRef = useRef<SpeechRecognitionLike | null>(null);
  const startRequestedRef = useRef(false);
  const listeningRef = useRef(false);
  const finalBufferRef = useRef<string>("");
  const finalDeliveredRef = useRef<boolean>(false);
  const endedRef = useRef<boolean>(true);
  const errorRef = useRef<boolean>(false);
  const stopWatchdogRef = useRef<number | null>(null);

  const clearStopWatchdog = () => {
    if (stopWatchdogRef.current !== null) {
      window.clearTimeout(stopWatchdogRef.current);
      stopWatchdogRef.current = null;
    }
  };

  const forceIdle = useCallback(() => {
    clearStopWatchdog();
    listeningRef.current = false;
    startRequestedRef.current = false;
    endedRef.current = true;
    setStatus((prev) => (prev === "error" ? prev : "idle"));
  }, []);

  const setLocale = useCallback((next: SpeechLocale) => {
    setLocaleState(next);
    setStoredLocale(next);
  }, []);

  const setAutoSend = useCallback((next: boolean) => {
    setAutoSendState(next);
    setStoredAutoSend(next);
  }, []);

  const resetTranscript = useCallback(() => {
    setTranscript("");
    setInterim("");
    finalBufferRef.current = "";
  }, []);

  const consumeFinalTranscript = useCallback(() => {
    const out = transcript.trim();
    setTranscript("");
    setInterim("");
    finalBufferRef.current = "";
    return out;
  }, [transcript]);

  const stop = useCallback(() => {
    logDebug("stop() called", {
      listening: listeningRef.current,
      ended: endedRef.current,
      status,
    });
    if (endedRef.current) {
      logDebug("stop(): already ended, noop");
      return;
    }
    const prevStatus = status;
    if (prevStatus === "listening") {
      setStatus("processing");
    }
    try {
      recogRef.current?.stop();
    } catch (e) {
      logDebug("stop() exception", e);
    }
    clearStopWatchdog();
    stopWatchdogRef.current = window.setTimeout(() => {
      logDebug("stop() watchdog fired – forcing idle");
      forceIdle();
    }, 2500);
  }, [status, forceIdle]);

  const createAndBind = useCallback(
    (currentLocale: SpeechLocale): SpeechRecognitionLike | null => {
      const Ctor = tryGetConstructor();
      if (!Ctor) return null;
      const r = new Ctor();
      r.lang = currentLocale;
      r.continuous = false;
      r.interimResults = true;
      r.maxAlternatives = 1;

      r.onstart = () => {
        logDebug("onstart");
        clearStopWatchdog();
        listeningRef.current = true;
        startRequestedRef.current = false;
        endedRef.current = false;
        errorRef.current = false;
        finalDeliveredRef.current = false;
        setError(null);
        setStatus("listening");
        setInterim("");
        finalBufferRef.current = "";
      };

      r.onresult = (ev) => {
        if (endedRef.current) {
          logDebug("onresult IGNORED (already ended)");
          return;
        }
        let interimPart = "";
        let finalPart = "";
        for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
          const alt = ev.results[i];
          const text = alt[0]?.transcript ?? "";
          if (alt.isFinal) {
            finalPart += text;
          } else {
            interimPart += text;
          }
        }
        if (finalPart) {
          finalBufferRef.current = (finalBufferRef.current + " " + finalPart).trim();
          logDebug("onresult final", {
            final: finalPart,
            buffer: finalBufferRef.current,
          });
          setTranscript(finalBufferRef.current);
        }
        if (interimPart) {
          logDebug("onresult interim", interimPart);
        }
        setInterim(interimPart.trim());
      };

      r.onspeechend = () => {
        logDebug("onspeechend → stop()");
        try {
          r.stop();
        } catch {
          /* ignore */
        }
      };

      r.onsoundend = () => {
        logDebug("onsoundend");
      };

      r.onaudioend = () => {
        logDebug("onaudioend");
      };

      r.onerror = (ev) => {
        const err = String(ev.error || "unknown");
        logDebug("onerror", err);
        errorRef.current = true;
        listeningRef.current = false;
        startRequestedRef.current = false;
        const userFacing = mapErrorToMessage(err);
        setError(userFacing);
        setStatus("error");
      };

      r.onend = () => {
        clearStopWatchdog();
        listeningRef.current = false;
        startRequestedRef.current = false;
        const hadError = errorRef.current;
        const finalText = finalBufferRef.current.trim();
        const alreadyDelivered = finalDeliveredRef.current;
        endedRef.current = true;
        logDebug("onend", { hadError, finalText, alreadyDelivered });
        setInterim("");
        if (!hadError && finalText && !alreadyDelivered) {
          finalDeliveredRef.current = true;
          logDebug("onend → delivering final transcript", finalText);
          onFinalRef.current?.(finalText);
        }
        if (!hadError && !finalText) {
          logDebug("onend → no final transcript, no-speech soft error");
          const softMsg = mapErrorToMessage("no-speech");
          setError(softMsg);
          setStatus("error");
          return;
        }
        setStatus((prev) => {
          if (prev === "error") return prev;
          return "idle";
        });
      };

      return r;
    },
    [],
  );

  const start = useCallback(() => {
    logDebug("start() requested");
    if (!supported) {
      setError("Hlasové zadávání není v tomto prohlížeči podporováno.");
      setStatus("error");
      return;
    }
    clearStopWatchdog();
    errorRef.current = false;
    finalDeliveredRef.current = false;
    setError(null);
    try {
      let recog = recogRef.current;
      if (!recog) {
        recog = createAndBind(locale);
        recogRef.current = recog;
      } else {
        recog.lang = locale;
      }
      if (!recog) {
        setError("Hlasové zadávání není v tomto prohlížeči podporováno.");
        setStatus("error");
        return;
      }
      setTranscript("");
      setInterim("");
      finalBufferRef.current = "";
      endedRef.current = false;
      startRequestedRef.current = true;
      setStatus("listening");
      recog.start();
    } catch (e) {
      logDebug("start() exception", e);
      listeningRef.current = false;
      startRequestedRef.current = false;
      endedRef.current = true;
      const msg = e instanceof Error ? e.message : String(e ?? "");
      setError(mapErrorToMessage(msg));
      setStatus("error");
    }
  }, [supported, locale, createAndBind]);

  useEffect(() => {
    if (recogRef.current) {
      try {
        recogRef.current.lang = locale;
      } catch {
        /* ignore */
      }
    }
  }, [locale]);

  useEffect(() => {
    return () => {
      logDebug("cleanup: abort + forceIdle");
      clearStopWatchdog();
      try {
        recogRef.current?.abort();
      } catch {
        /* ignore */
      }
      listeningRef.current = false;
      startRequestedRef.current = false;
      endedRef.current = true;
    };
  }, []);

  return {
    supported,
    status,
    transcript,
    interim,
    error,
    locale,
    autoSend,
    setLocale,
    setAutoSend,
    start,
    stop,
    resetTranscript,
    consumeFinalTranscript,
  };
}

export function mapErrorToMessage(errorCode: string): string {
  const code = String(errorCode || "").toLowerCase();
  switch (code) {
    case "not-allowed":
    case "permission-denied":
    case "service-not-allowed":
      return "Přístup k mikrofonu byl odepřen. Povol ho v nastavení prohlížeče.";
    case "no-speech":
      return "Nebyla rozpoznána žádná řeč. Zkus to znovu.";
    case "audio-capture":
      return "Nebyl nalezen žádný mikrofon. Připoj zařízení a zkus to znovu.";
    case "network":
      return "Hlasové zadávání potřebuje síťové připojení.";
    case "aborted":
      return "Nahrávání bylo přerušeno.";
    case "language-not-supported":
      return "Vybraný jazyk pro rozpoznávání řeči není podporován.";
    default:
      if (code) return `Chyba při rozpoznávání řeči (${code}). Zkus to znovu.`;
      return "Nastala chyba při rozpoznávání řeči. Zkus to znovu.";
  }
}
