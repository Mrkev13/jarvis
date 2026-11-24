# Jarvis – hlasové pozdravy (MRK-136)

Předgenerované krátké pozdravy pro start systému, vytvořené offline nástrojem
[Piper](https://github.com/rhasspy/piper) (neuronový TTS, běží lokálně, nic se neposílá ven).
Aplikace je přehrává jako výchozí „studiový hlas“; hlasy prohlížeče zůstávají jako volba v Nastavení.

| soubor | text | hlas (Piper) | licence datové sady |
|---|---|---|---|
| `en-morning.mp3` … `en-night.mp3` | „Good morning / afternoon / evening, Standa. All systems online.“, v noci „Burning the midnight oil, Standa? …“ | `en_GB-northern_english_male-medium` | CC BY-SA 4.0 – [OpenSLR 83](http://www.openslr.org/83/) (Google, „Crowdsourced high-quality UK and Ireland English Dialect speech data set“) |
| `cs-morning.mp3` … `cs-night.mp3` | „Dobré ráno / odpoledne, Dobrý večer, Stando. Všechny systémy jsou online.“, v noci „Pořád vzhůru, Stando? …“ | `cs_CZ-jirka-medium` | CC0 |

Generování (2026-11-24): `piper --length-scale 1.06`, pak `ffmpeg -af "highpass=f=90,aecho=0.8:0.6:35:0.12,loudnorm=I=-18:TP=-2"`,
mono 22,05 kHz, MP3 64 kb/s. Texty musí odpovídat `greetingText()` v `lib/hudVoice.ts`.
Hlas „Alan“ (en_GB) se nepoužil – datová sada je „All Rights Reserved“.
