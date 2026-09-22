# Device protocol

How each byte was established, so the next person does not start over.

<!-- For every field: where it sits, what it means, and what it was verified
     against - a real device, the vendor app, a capture. A field that was
     guessed says so. -->

## Transport

<!-- HTTP, BLE GATT, MQTT, a serial line. Addresses, UUIDs, endpoints. -->

## Frames

| Offset | Length | Meaning | Verified against |
|-------:|-------:|---------|------------------|
| 0 | 1 | | |

## Commands

<!-- What can be written, and what the device answers. -->

## Deliberately absent

<!-- Commands that are known and are not implemented, with the reason. A
     factory reset that is merely undocumented gets added back by the next
     helpful contributor; one that is documented as excluded does not. -->
