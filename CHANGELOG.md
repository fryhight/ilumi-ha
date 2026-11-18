# Changelog

## 0.4.4

**Changed**
- **Add bulb:** a bulb recognised by its advertised service but without a heard name is listed as "Ilumi bulb" (not "no name"), and the name field is pre-filled with "Ilumi".
- The list shows the raw advertisement data of a device as hex (manufacturer data, service data, TX power). This is meant to find out whether A19 and BR30 bulbs send different bytes, so that the shape could be read automatically later.

## 0.4.3

**Changed**
- **Add bulb** also recognises a bulb by the Ilumi service in its advertisement, not only by its name, because Home Assistant often does not hear the name.
- Devices without a name now show what they send besides the address (manufacturer id and service ids, e.g. `[mfr 0059; uuid f000f0c0]`). This helps to tell the bulbs apart from other devices.

## 0.4.2

**Fixed**
- **Add bulb** did not list bulbs whose Bluetooth name Home Assistant had not heard (it then shows the address in place of the name). The dialog now asks for five seconds of active scanning before it builds the list, because names are only sent in the scan response. If no bulb with a name is found, the list shows the devices without a name, not every device nearby. "Show all Bluetooth devices" is still there.

## 0.4.1

**Changed**
- When **Add bulb** does not recognise a bulb by its Bluetooth name, it now lists all Bluetooth devices that Home Assistant hears (strongest signal first, unnamed ones marked) instead of showing an empty address field. There is also a "Show all Bluetooth devices" entry in the normal list. That shows at once whether Home Assistant hears a bulb and under which name.

## 0.4.0

One entry for all bulbs. Contains everything from 0.3.0 too, which was never released on its own.

**Changed (action needed when upgrading from 0.2.x)**
- There is now **one** Ilumi entry that holds the network key. Every bulb is a sub-entry of it and shows up as its own device, added with **Add bulb**. Before, every bulb was a separate entry.
- Delete the old per-bulb entries before updating, reset your bulbs (switch off and on five times) and add them again under the new entry.

**New**
- Bulb shape: pick **A19** or **BR30** per bulb. It sets the model of the device, and the BR30 gets a spot-bulb icon. Name and shape can be edited later on the bulb.
- **Effects:** the 17 effects of the original app (Aurora, Ocean, Fireworks, Galaxy, Forest, Volcanic, ...) and a **Candle** mode, chosen in the light's *Effect* menu. The colour list is uploaded to the bulb once and the bulb plays it by itself until you choose a colour, another effect or switch it off. The brightness slider dims the effect. (0.3.0)

## 0.2.1

**Fixed**
- A bulb that comes back after a power cut could stay "unavailable". Home Assistant only reports changed Bluetooth advertisements, so the integration now also asks every 15 seconds whether the bulb is heard.

## 0.2.0

**New**
- Bulbs are set up from Home Assistant itself: reset a bulb (five times off and on), pick it from the list, done. The integration writes the shared network key into the bulb. A set up bulb starts bright white without the red-green-blue-white startup animation.
- A bulb that loses power becomes "unavailable" and comes back as "on, bright white", so Adaptive Lighting can set the right colour. Home Assistant needs up to about five minutes to notice a bulb that is gone.
- Bulb pick list with signal strength, German and English texts.
- The Ilumi app icon is shown as the integration icon (Home Assistant 2026.3 or newer).

**Fixed**
- The short white flash when switching a bulb on from Home Assistant is gone. Colour and brightness alone now switch the bulb on, off is brightness 0.
- Colour brightness and white brightness sliders dim as expected.

## 0.1.0

First version: on/off, RGBW colour, brightness, several bulbs through Home Assistant's Bluetooth or an ESPHome Bluetooth proxy.
