# Ilumi Bluetooth Bulbs for Home Assistant

Local control of the Ilumi Bluetooth bulbs (Kickstarter "Ilumi", the vendor and its app are gone) in Home Assistant. No cloud, no account, no MQTT, no extra hardware. The bulbs are reached through Home Assistant's own Bluetooth, which includes ESPHome Bluetooth proxies.

*Ilumi-Bluetooth-Birnen lokal in Home Assistant steuern, ohne Cloud, ohne Konto, ohne MQTT. Die deutsche Kurzanleitung steht unten.*

## Features

- RGBW colour and brightness, on/off, assumed state
- Works with Adaptive Lighting and scenes
- Bulbs are set up from Home Assistant itself: reset a bulb, pick it from the list, done
- One Bluetooth connection at a time, picks the best adapter or proxy by itself
- A bulb that loses power becomes unavailable and comes back as "on, bright white"

## Requirements

- Home Assistant with working Bluetooth (adapter or ESPHome Bluetooth proxy)
- Home Assistant 2026.3 or newer for the integration icon (the rest works with older versions, but it is only tested on a recent one)

## Install

With [HACS](https://hacs.xyz): *HACS → three dots → Custom repositories* → add `https://github.com/fryhight/ilumi-ha` as type *Integration*, download it, restart Home Assistant.

Manually: copy `custom_components/ilumi` into `/config/custom_components/` and restart.

## Add a bulb

1. Reset the bulb: switch it off and on **five times** in a row. It runs red, green, blue, white. It now has network key 0.
2. *Settings → Devices & services → Add integration → Ilumi Bluetooth Bulbs*.
3. Pick the bulb from the list. The closest bulb has the strongest signal.
4. Give it a name and leave "Set up the bulb now" ticked. The key is chosen for you. All bulbs share one key, later bulbs reuse the key of the first one.

A bulb that is set up starts bright white without the red-green-blue-white startup animation. A bulb that was never set up (key 0) plays the animation at every power-up.

Untick "Set up the bulb now" only for a bulb that already has the key you enter.

## Notes and limits

- The state is assumed. The bulb is not read back.
- Several bulbs in one scene are sent one after the other, about one to two seconds per bulb.
- A very short power cut may go unnoticed. Home Assistant then still shows the old state until the next command.
- Setting up writes a network key into the bulb. The protocol is taken from the reverse-engineered [ilumi-sdk](https://github.com/GimpyHand/ilumi-sdk), which warns that wrong setup commands can lock a bulb for good. This integration sends exactly the command that SDK sends.
- Not affiliated with Ilumi. The logo belongs to its owners.

## Kurzanleitung (Deutsch)

1. In HACS als benutzerdefiniertes Repository (Typ *Integration*) `https://github.com/fryhight/ilumi-ha` hinzufügen, herunterladen, Home Assistant neu starten.
2. Neue Birne zurücksetzen: fünfmal schnell aus- und einschalten (Rot, Grün, Blau, Weiß).
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Ilumi Bluetooth Bulbs*, Birne in der Liste wählen, Namen eingeben, das Häkchen "Birne jetzt einrichten" lassen.
4. Eingerichtete Birnen starten ohne Animation direkt in hellem Weiß. Zurückgesetzte Birnen (Schlüssel 0) spielen die Animation bei jedem Einschalten ab.

Alle Birnen teilen sich einen Schlüssel. Er wird dir beim ersten Mal vorgeschlagen und danach wiederverwendet.
