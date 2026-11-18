# Ilumi Bluetooth Bulbs for Home Assistant

Local control of the Ilumi Bluetooth bulbs (Kickstarter "Ilumi", the vendor and its app are gone) in Home Assistant. No cloud, no account, no MQTT, no extra hardware. The bulbs are reached through Home Assistant's own Bluetooth, which includes ESPHome Bluetooth proxies.

## Features

- RGBW colour and brightness, on/off, assumed state
- Works with Adaptive Lighting and scenes
- Bulbs are set up from Home Assistant itself: reset a bulb, pick it from the list, done
- One Bluetooth connection at a time, picks the best adapter or proxy by itself
- A bulb that loses power becomes unavailable and comes back as "on, bright white"
- Effects: the 17 effects of the original app (aurora, ocean, fireworks, ...) and a candle mode, chosen in the light's *Effect* menu. The bulb stores and plays them itself

## Requirements

- Home Assistant with working Bluetooth (adapter or ESPHome Bluetooth proxy)
- Home Assistant 2026.3 or newer for the integration icon (the rest works with older versions, but it is only tested on a recent one)

## Install

With [HACS](https://hacs.xyz): *HACS → three dots → Custom repositories* → add `https://github.com/fryhight/ilumi-ha` as type *Integration*, download it, restart Home Assistant.

Manually: copy `custom_components/ilumi` into `/config/custom_components/` and restart.

## Set up

1. *Settings → Devices & services → Add integration → Ilumi Bluetooth Bulbs*. A network key is suggested, keep it. All bulbs share this one key. There is only one Ilumi entry, all bulbs are added under it.

## Add a bulb

1. Reset the bulb: switch it off and on **five times** in a row. It runs red, green, blue, white. It now has network key 0.
2. On the Ilumi entry click **Add bulb**.
3. Pick the bulb from the list. The closest bulb has the strongest signal.
4. Give it a name, pick its shape (A19 or BR30) and leave "Set up the bulb now" ticked. The bulb lights up white when it worked.

A bulb that is set up starts bright white without the red-green-blue-white startup animation. A bulb that was never set up (key 0) plays the animation at every power-up.

Untick "Set up the bulb now" only for a bulb that already has the key of the entry. The name and the shape can be changed later on the bulb's own menu. The shape sets the model in the device and a fitting icon for the light.

If you upgrade from 0.2 or 0.3: those versions made one entry per bulb. Delete those entries, add Ilumi once as described above, reset your bulbs (five times off and on) and add them again.

## Effects

Open a light and pick an effect. The integration sends the colour list to the bulb once, the bulb then plays it on its own and keeps playing it until you choose a colour, another effect or switch it off. The brightness slider dims the effect. *Candle* flickers in the colour you chose.

Several bulbs with the same effect do not run in step, each starts when its list arrives. The effect colour lists are taken from [ilumi-sdk](https://github.com/GimpyHand/ilumi-sdk) (MIT licence), which took them from the original app.

## Notes and limits

- The state is assumed. The bulb is not read back.
- Several bulbs in one scene are sent one after the other, about one to two seconds per bulb.
- A very short power cut may go unnoticed. Home Assistant then still shows the old state until the next command.
- Setting up writes a network key into the bulb. The protocol is taken from the reverse-engineered [ilumi-sdk](https://github.com/GimpyHand/ilumi-sdk), which warns that wrong setup commands can lock a bulb for good. This integration sends exactly the command that SDK sends.
- Not affiliated with Ilumi. The logo belongs to its owners.
