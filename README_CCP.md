# J745 CCP Dataset Reader

Capture raw BIN datasets from VW PQ J745 at address 55, SW `5M0 907 357 F / 0111`, with the Linux SocketCAN reader.

For XML editing, see the [main README](README.md).

## Connect to Ext-CAN

Connect the CAN adapter **directly to the Ext-CAN bus used by J745** and configure **500 kbit/s (500,000 bit/s)**. Use the vehicle wiring diagram to identify Ext-CAN CAN-H and CAN-L. Keep the module on a bench or the vehicle stationary while capturing. The OBD gateway can pass UDS while filtering the extended CCP frames.

The reader uses CCP 2.1 over classic CAN and opens an existing Linux SocketCAN interface. For a SocketCAN adapter named `can0`, set its bitrate before starting the reader.

```sh
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details link show can0
```

| Transport | Tester request | J745 response |
| --- | --- | --- |
| Physical UDS over ISO-TP | `0x754` | `0x7BE` |
| CCP raw CAN, 29-bit, DLC 8 | `0x07FEA600` | `0x07FEA601` |

## Enable CCP access

1. Confirm that address 55 is J745 with software `5M0 907 357 F / 0111`. Use an authorized UDS tester.
2. Read `22 09 02`. If the response is `62 09 02 01`, CCP is already enabled. If it is `62 09 02 00`, save that original value and continue.
3. Open extended diagnostic session `10 03`. Complete the tester's authorized SecurityAccess workflow and use its valid workshop fingerprint and date.
4. Write `2E 09 02 01`, wait for `6E 09 02` and read `22 09 02` again. `62 09 02 01` confirms that CCP is enabled. This changes an adaptation stored in nonvolatile memory.

The requests above are UDS payloads. Let the diagnostic tester handle ISO-TP framing. If CCP times out, check the direct Ext-CAN connection, the bitrate and DID `0902` before retrying.

## Capture RAM first

Run from the repository root. Replace `can0` with your SocketCAN interface. Each output directory must be new.

```sh
mkdir -p captures
python3 read_j745_dataset.py capture --interface can0 --out captures/j745-ram
python3 read_j745_dataset.py inspect captures/j745-ram/ram_1.bin
```

The reader connects to station `0x0039`, checks CCP version and the selected calibration page, then reads 1,520 bytes from `0xFFFFE900`. Each pass uses 304 five-byte CCP reads. It saves two independent passes as `ram_1.bin` and `ram_2.bin`, a `manifest.json` with page flags, CRC and SHA-256, and a `can_trace.jsonl` with the exchange. The RAM is the currently selected dataset when the manifest reports `ram_is_selected_page: true`.

## CCP frame reference

For a manual RAM read over raw CAN, send these eight-byte payloads individually to `0x07FEA600` as extended frames. Before each new request, wait for `FF 00 <counter>` in the matching reply from `0x07FEA601`.

| Payload | Command |
| --- | --- |
| `01 00 39 00 00 00 00 00` | Connect to station `0x0039` |
| `1B 01 02 01 00 00 00 00` | Check for CCP version 2.1 |
| `09 02 00 00 00 00 00 00` | Read the selected calibration page |
| `0F 03 05 00 00 E9 FF FF` | Read the first five RAM bytes |

Use `0F <counter> 05 00 <address LE32>` for each next block. Advance the address by five and wrap the counter at 256. Append the five bytes after the reply header. A full pass covers `0xFFFFE900..0xFFFFEEEF`. Check the page before and after each full pass and compare two passes byte for byte.

## Capture the saved copy

```sh
python3 read_j745_dataset.py capture --interface can0 --saved --out captures/j745-ram-and-saved
python3 read_j745_dataset.py inspect captures/j745-ram-and-saved/saved_1.bin
```

This also captures RAM, temporarily selects the stored calibration page at `0x00FF8000`, and attempts to restore the original page even if the read fails. Capture with `--saved` changes the active page during the read. Confirm `success: true` and `page_restored: true` in the manifest. After a transport loss or interrupted process, verify the page through the diagnostic connection before leaving the bench or moving the vehicle.

## Check the capture and restore access

- Expect exactly **1,520 bytes**, header `65 12 27 70`, valid CRC, and matching copies for each source. The checksum covers the first 1,518 bytes. The last two bytes store the CRC in little-endian order.
- Keep RAM and saved files separate. The CLI's `inspect` command reports integrity and the activation and two DLA switch-off speeds. The editor takes parameterization XML. Use a matching XML packaging workflow to prepare a captured BIN for editing.
- If you enabled CCP for the capture, restore the original adaptation with the authorized tester after verifying the original page. For an original value of `00`, write `2E 09 02 00`, then confirm `62 09 02 00` with `22 09 02`.

The RAM workflow was verified on a `5M0 907 357 F / 0111` unit with two identical CRC-valid passes. Saved-page selection and restoration were verified against a simulated ECU.
