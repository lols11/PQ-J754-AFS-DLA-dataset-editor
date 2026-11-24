#!/usr/bin/env python3
"""Read J745/0111 parameters over classic SocketCAN CCP, or inspect a dump offline.

This tool never changes adaptations or writes parameter bytes. --saved temporarily
selects the saved calibration page and restores the original page before exit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import time

LENGTH = 0x5F0
RAM = 0xFFFFE900
SAVED = 0x00FF8000
FACTORY = 0x0003F000
FLAGS = 0xFFFFE50E
CRO = 0x07FEA600
DTO = 0x07FEA601
CAN_FRAME = struct.Struct("=IB3x8s")


def crc16(data):
    """Firmware's reflected 0x1021 CRC: init FFFF, polynomial 8408, no xorout."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return crc


def inspect_block(data):
    result = {"length": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "valid": False}
    if len(data) != LENGTH:
        result["error"] = "Expected exactly 1520 bytes"
        return result
    stored = int.from_bytes(data[-2:], "little")
    computed = crc16(data[:-2])
    result.update(header=data[:4].hex(" "), header_valid=data[:4] == bytes.fromhex("65 12 27 70"),
                  crc_stored=f"0x{stored:04X}", crc_computed=f"0x{computed:04X}",
                  crc_valid=stored == computed,
                  speed_parameters=[{"offset": f"0x{offset:X}",
                                     "bytes_le": data[offset:offset + 2].hex(" "),
                                     "raw_s16": struct.unpack_from("<h", data, offset)[0],
                                     "km_h": struct.unpack_from("<h", data, offset)[0] / 100}
                                    for offset in (0x368, 0x36A, 0x36C)])
    result["valid"] = result["header_valid"] and result["crc_valid"]
    return result


class SocketCan:
    def __init__(self, interface, trace, timeout):
        self.timeout = timeout
        self.trace = trace
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            mask = socket.CAN_EFF_FLAG | socket.CAN_RTR_FLAG | socket.CAN_EFF_MASK
            self.sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER,
                                 struct.pack("=II", DTO | socket.CAN_EFF_FLAG, mask))
            self.sock.bind((interface,))
        except BaseException:
            self.sock.close()
            raise

    def log(self, direction, can_id, data):
        self.trace.write(json.dumps({"time_ns": time.time_ns(), "direction": direction,
                                     "can_id": f"0x{can_id:08X}",
                                     "payload": data.hex(" ")}) + "\n")
        self.trace.flush()

    def exchange(self, request):
        self.sock.send(CAN_FRAME.pack(CRO | socket.CAN_EFF_FLAG, 8, request))
        self.log("tx", CRO, request)
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("No matching CCP response")
            self.sock.settimeout(remaining)
            raw = self.sock.recv(CAN_FRAME.size)
            if len(raw) != CAN_FRAME.size:
                raise RuntimeError("Unexpected SocketCAN frame size")
            ident, length, data = CAN_FRAME.unpack(raw)
            if ident != (DTO | socket.CAN_EFF_FLAG):
                continue
            self.log("rx", DTO, data[:length])
            if length != 8:
                raise RuntimeError("CCP response DLC must be 8")
            if data[0] == 0xFF and data[2] == request[1]:
                return data

    def close(self):
        self.sock.close()


class CcpReader:
    def __init__(self, exchange):
        self.exchange = exchange
        self.counter = 0

    def command(self, opcode, payload=b""):
        if opcode not in (0x01, 0x02, 0x09, 0x0F, 0x11, 0x1B):
            raise ValueError("Command is outside the reader's allowlist")
        if len(payload) > 6:
            raise ValueError("CCP payload is too long")
        request = bytes((opcode, self.counter)) + payload.ljust(6, b"\0")
        self.counter = (self.counter + 1) & 255
        response = self.exchange(request)
        if len(response) != 8 or response[0] != 0xFF or response[2] != request[1]:
            raise RuntimeError("Malformed or mismatched CCP response")
        if response[1] != 0:
            raise RuntimeError(f"CCP command 0x{opcode:02X}: status 0x{response[1]:02X}")
        return response[3:]

    def connect(self):
        self.command(0x01, bytes.fromhex("39 00"))
        version = self.command(0x1B, bytes((2, 1)))[:2]
        if version != bytes((2, 1)):
            raise RuntimeError(f"Unexpected CCP version: {version.hex(' ')}")

    def page(self):
        # GET_ACTIVE_CAL_PAGE has one address-extension byte before the u32.
        data = self.command(0x09)
        if data[0] != 0:
            raise RuntimeError("Unexpected calibration address extension")
        return int.from_bytes(data[1:], "little")

    def select_page(self, page):
        if page not in (RAM, SAVED, FACTORY):
            raise ValueError("Unsupported calibration page")
        # Firmware selects factory fallback through the saved-page selector.
        selector = SAVED if page == FACTORY else page
        self.command(0x02, bytes((0, 0)) + selector.to_bytes(4, "little"))
        self.command(0x11)
        actual = self.page()
        if actual != page:
            raise RuntimeError(f"Page selection failed: wanted 0x{page:08X}, got 0x{actual:08X}")

    def read(self, address, length):
        if length < 0 or address < 0 or address + length > 0x100000000:
            raise ValueError("Invalid memory range")
        result = bytearray()
        while len(result) < length:
            count = min(5, length - len(result))
            payload = bytes((count, 0)) + (address + len(result)).to_bytes(4, "little")
            result.extend(self.command(0x0F, payload)[:count])
        return bytes(result)


def capture(reader, out, saved=False):
    """Store both passes before interpreting integrity; always attempt page cleanup."""
    metadata = {"proof_level": "live CCP capture; firmware identity must be checked separately",
                "captures": {}, "success": False, "saved_requested": saved,
                "adaptations_changed_by_tool": False,
                "parameter_bytes_written_by_tool": False}
    original = None
    restore_needed = False
    try:
        reader.connect()
        original = reader.page()
        if original not in (RAM, SAVED, FACTORY):
            raise RuntimeError(f"Unknown initial calibration page 0x{original:08X}")
        metadata["original_page"] = f"0x{original:08X}"
        metadata["flags_before"] = reader.read(FLAGS, 1)[0]

        def pair(name, address, expected_page):
            blobs = []
            for n in (1, 2):
                if reader.page() != expected_page:
                    raise RuntimeError("Calibration page changed during capture")
                blob = reader.read(address, LENGTH)
                path = out / f"{name}_{n}.bin"
                with path.open("xb") as stream:
                    stream.write(blob)
                metadata["captures"][path.name] = inspect_block(blob)
                blobs.append(blob)
                if reader.page() != expected_page:
                    raise RuntimeError("Calibration page changed during capture")
            metadata[f"{name}_stable"] = blobs[0] == blobs[1]
            if blobs[0] != blobs[1]:
                raise RuntimeError(f"Two {name} reads differ; raw files preserved")
            if not all(metadata["captures"][f"{name}_{n}.bin"]["valid"] for n in (1, 2)):
                raise RuntimeError(f"Invalid {name} header or CRC; raw files preserved")
            return blobs[0]

        ram = pair("ram", RAM, original)
        metadata["ram_is_selected_page"] = original == RAM
        if saved:
            if reader.read(FLAGS, 1)[0] & 0x0E:
                raise RuntimeError("Saved copy has fallback/CRC/header error flags; refusing to relabel an alias as saved data")
            restore_needed = original != SAVED
            reader.select_page(SAVED)
            stored = pair("saved", SAVED, SAVED)
            metadata["ram_equals_saved"] = ram == stored
        metadata["flags_after"] = reader.read(FLAGS, 1)[0]
        metadata["success"] = True
    except BaseException as exc:
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            if restore_needed:
                reader.select_page(original)
            if original is not None:
                actual = reader.page()
                metadata["final_page"] = f"0x{actual:08X}"
                if actual != original:
                    raise RuntimeError("Original calibration page was not restored")
                metadata["page_restored"] = True
                metadata["final_flags"] = reader.read(FLAGS, 1)[0]
        except BaseException as exc:
            metadata["success"] = False
            metadata["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            (out / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    inspect = sub.add_parser("inspect", help="Validate a 1520-byte dump offline")
    inspect.add_argument("file", type=Path)
    live = sub.add_parser("capture", help="Read CCP; does not enable DID 0902")
    live.add_argument("--interface", required=True, help="Already configured SocketCAN interface")
    live.add_argument("--out", required=True, type=Path, help="New output directory; never overwritten")
    live.add_argument("--saved", action="store_true", help="Also read saved copy; temporarily select its page")
    live.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    if args.action == "inspect":
        result = inspect_block(args.file.read_bytes())
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 2
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    args.out.mkdir(parents=True, exist_ok=False)
    with (args.out / "can_trace.jsonl").open("x") as trace:
        try:
            bus = SocketCan(args.interface, trace, args.timeout)
        except OSError as exc:
            (args.out / "manifest.json").write_text(json.dumps({
                "success": False, "stage": "socket_open", "interface": args.interface,
                "error": f"{type(exc).__name__}: {exc}"}, indent=2) + "\n")
            raise
        try:
            result = capture(CcpReader(bus.exchange), args.out, args.saved)
        finally:
            bus.close()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
