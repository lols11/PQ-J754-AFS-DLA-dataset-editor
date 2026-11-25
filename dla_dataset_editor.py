#!/usr/bin/env python3
# SPDX-License-Identifier: MIT AND Beerware
"""Edit DLA speed thresholds and cornering light DTCs in J745 dataset XML files."""

import argparse
import re
import struct
import sys
import webbrowser
from pathlib import Path
from xml.parsers import expat


TITLE = "DLA Dataset Editor"
VERSION = "1.0.6"
FREE_TEXT = "FREE FOR ALL."
AUTHOR_TEXT = f"BY LOLS11   v{VERSION}"
SUPPORT_TEXT = "If you want to support me or check out my work"
SUPPORT_URL = "https://linktr.ee/lols11"
LICENSE_TEXT = """DLA Dataset Editor is licensed under both licenses below. Both sets of terms apply.

MIT License

Copyright (c) 2026 lols11

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

"THE BEER-WARE LICENSE" (Revision 42)

lols11 wrote this software. As long as you retain this notice, you can
do whatever you want with this software. If we meet some day and you
think this software is worth it, you can buy me a beer in return.

lols11
"""
CLI_BANNER = (
    f"{TITLE.upper()} | VW PQ AFS / DLA\n"
    f"{FREE_TEXT} {AUTHOR_TEXT}\n"
    "J745 dataset XML editor for 5M0 907 357 F / 0111.\n"
    "OFF-ROAD USE ONLY. This software is provided as is, without warranty.\n"
    "Uploading a dataset clears the J745 coding and invalidates the headlamp basic setting.\n"
    f"{SUPPORT_TEXT}, visit {SUPPORT_URL}"
)
FIELDS = (
    (0x368, "DLA activation speed"),
    (0x36A, "DLA off speed (either lamp outside full high beam)"),
    (0x36C, "DLA off speed (both lamps at full high beam)"),
    (0x36E, "Street lighting inhibit speed"),
    # Object indicator E066 only increases at or above this speed (0x17AFC..0x17B3A).
    (0x3B8, "DLA object indicator min speed"),
    # Speed axis of the steering-activity gain table +0x204 (0x2885A). Gain is 0% at or below
    # the first point and 100% from the second point; the third point stays at +0x20E.
    (0x20A, "Curve detection gain axis start (0%)"),
    (0x20C, "Curve detection gain axis full (100%)"),
)
# Suggested raw values (0.01 km/h) for DLA from 30 km/h; fields not listed keep their current value.
SUGGESTED = {0x368: 3000, 0x36A: 2700, 0x36C: 2500, 0x3B8: 3000, 0x20A: 3000, 0x20C: 4000}
CURVE_AXIS = (0x20A, 0x20C, 0x20E)
DTC_LIST_OFFSET = 0x468
DTC_LIST_FORMAT = "<5H"
EMPTY_DTC_SLOT = 0xFFFF
CORNERING_DTC_GROUPS = (
    ("Left bulb", (
        (0x46, "C1083 11 · Short to ground"),
        (0x48, "C1083 13 · Open circuit"),
    )),
    ("Right bulb", (
        (0x47, "C1084 11 · Short to ground"),
        (0x49, "C1084 13 · Open circuit"),
    )),
)
# J745 event indices for C1083 11, C1084 11, C1083 13 and C1084 13.
CORNERING_DTC_EVENTS = tuple(sorted(event for _, group in CORNERING_DTC_GROUPS for event, _ in group))
DATASET_ATTRIBUTES = {
    "DIAGNOSTIC_ADDRESS": "0x0055",
    "START_ADDRESS": "0x000001",
}
BYTE_TOKEN = re.compile(rb"0[xX][0-9A-Fa-f]{2}")
PAYLOAD = re.compile(rb"\s*0[xX][0-9A-Fa-f]{2}(?:\s*,\s*0[xX][0-9A-Fa-f]{2})*\s*")
SPEED = re.compile(r"([0-9]{1,3})(?:[.,]([0-9]{1,2}))?")
CRC_OFFSET = 0x5EE


def crc16(data):
    """J745 CRC-16 with reflected polynomial 0x8408, init 0xFFFF, xorout 0."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return crc


def parse_speed(text, current):
    text = text.strip()
    if not text:
        return current
    match = SPEED.fullmatch(text)
    if match:
        whole, fraction = match.groups()
        raw = int(whole) * 100 + int((fraction or "").ljust(2, "0"))
        if raw <= 32767:
            return raw
    raise ValueError("Enter 0 to 327.67 km/h with up to two decimal places.")


def speed_text(raw):
    return f"{raw / 100:.2f}"


class Dataset:
    def __init__(self, xml):
        self.xml = xml
        parser = expat.ParserCreate()
        attributes = None
        in_payload = False
        start = end = None

        def start_element(name, attrs):
            nonlocal attributes, in_payload
            if in_payload:
                raise ValueError("PARAMETER_DATA must contain a byte list.")
            if name == "PARAMETER_DATA":
                if attributes is not None:
                    raise ValueError("XML contains more than one PARAMETER_DATA block.")
                attributes = attrs
                in_payload = True

        def character_data(_text):
            nonlocal start
            if in_payload and start is None:
                start = parser.CurrentByteIndex

        def end_element(name):
            nonlocal end, in_payload
            if name == "PARAMETER_DATA":
                end = parser.CurrentByteIndex
                in_payload = False

        def reject_doctype(*_args):
            raise ValueError("Dataset XML contains a DOCTYPE declaration.")

        parser.StartElementHandler = start_element
        parser.CharacterDataHandler = character_data
        parser.EndElementHandler = end_element
        parser.StartDoctypeDeclHandler = reject_doctype
        try:
            parser.Parse(xml, True)
        except expat.ExpatError as exc:
            raise ValueError(f"Invalid XML ({exc}).") from exc

        if attributes is None:
            raise ValueError("PARAMETER_DATA block missing.")
        if any(attributes.get(name) != value for name, value in DATASET_ATTRIBUTES.items()):
            raise ValueError("Use a dataset for diagnostic address 0x55, block 1.")
        if start is None or not PAYLOAD.fullmatch(xml[start:end]):
            raise ValueError("PARAMETER_DATA must contain a list of 0xNN bytes.")
        self.tokens = tuple(BYTE_TOKEN.finditer(xml, start, end))
        self.payload = bytes(int(token.group(), 16) for token in self.tokens)
        if len(self.payload) != 0x5F0 or self.payload[:4] != bytes.fromhex("65 12 27 70"):
            raise ValueError("Invalid J745 block length or header.")
        self.crc = int.from_bytes(self.payload[CRC_OFFSET:], "little")
        computed = crc16(self.payload[:CRC_OFFSET])
        if self.crc != computed:
            raise ValueError(f"CRC mismatch (stored 0x{self.crc:04X}, calculated 0x{computed:04X}).")
        self.speeds = tuple(struct.unpack_from("<h", self.payload, offset)[0] for offset, _ in FIELDS)
        self.dtc_slots = struct.unpack_from(DTC_LIST_FORMAT, self.payload, DTC_LIST_OFFSET)

    def dtc_status(self):
        count = len(set(CORNERING_DTC_EVENTS).intersection(self.dtc_slots))
        return f"{count} of 4 cornering light DTCs suppressed."

    def save(self, destination, entries, suppressed_dtcs=None):
        payload = bytearray(self.payload)
        for (offset, label), entry, current in zip(FIELDS, entries, self.speeds):
            try:
                raw = parse_speed(entry, current)
            except ValueError as exc:
                raise ValueError(f"{label}: {exc}") from exc
            struct.pack_into("<h", payload, offset, raw)
        axis_bytes = slice(CURVE_AXIS[0], CURVE_AXIS[-1] + 2)
        if payload[axis_bytes] != self.payload[axis_bytes]:
            # The firmware looks up this axis with a binary search, so it must rise strictly.
            axis = [struct.unpack_from("<h", payload, offset)[0] for offset in CURVE_AXIS]
            if not axis[0] < axis[1] < axis[2]:
                raise ValueError(
                    "Curve detection axis must rise: "
                    + " < ".join(speed_text(raw) for raw in axis)
                    + f" km/h (last point 0x{CURVE_AXIS[-1]:03X} is fixed)."
                )
        if suppressed_dtcs is not None:
            slots = [
                EMPTY_DTC_SLOT if event in CORNERING_DTC_EVENTS and event not in suppressed_dtcs else event
                for event in self.dtc_slots
            ]
            missing = [event for event in CORNERING_DTC_EVENTS if event in suppressed_dtcs and event not in slots]
            free = [index for index, event in enumerate(slots) if event == EMPTY_DTC_SLOT]
            if len(free) < len(missing):
                raise ValueError("Too few free slots for the selected DTCs. Other entries are preserved.")
            for index, event in zip(free, missing):
                slots[index] = event
            struct.pack_into(DTC_LIST_FORMAT, payload, DTC_LIST_OFFSET, *slots)
        struct.pack_into("<H", payload, CRC_OFFSET, crc16(payload[:CRC_OFFSET]))

        xml = bytearray(self.xml)
        for index, (before, after) in enumerate(zip(self.payload, payload)):
            if before != after:
                token = self.tokens[index]
                xml[token.start() + 2:token.end()] = f"{after:02X}".encode("ascii")

        # Exclusive creation also protects the source if it is selected as the destination.
        output = destination.open("xb")
        try:
            with output:
                output.write(xml)
            saved_xml = destination.read_bytes()
            saved = Dataset(saved_xml)
            if saved_xml != xml or saved.payload != payload:
                raise OSError("Saved file failed readback verification.")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return saved


def next_output(path):
    candidate = path.with_name(f"{path.stem}_DLA.xml")
    number = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_DLA_{number}.xml")
        number += 1
    return candidate


def run_cli(args):
    print(CLI_BANNER, file=sys.stderr, flush=True)
    path = args.xml or Path(input("Dataset XML path: ").strip().strip('"'))
    dataset = Dataset(path.read_bytes())
    print(f"Input CRC 0x{dataset.crc:04X}. {dataset.dtc_status()}")
    suppressed_dtcs = None
    if args.cornering_dtc:
        entries = [""] * len(FIELDS)
        suppressed_dtcs = CORNERING_DTC_EVENTS if args.cornering_dtc == "suppress" else ()
    else:
        print("Press Enter to keep the current value.")
        entries = [
            input(f"{label} [{speed_text(raw)} km/h]: ")
            for (_, label), raw in zip(FIELDS, dataset.speeds)
        ]
    destination = args.output or next_output(path)
    saved = dataset.save(destination, entries, suppressed_dtcs)
    print(f"Saved {destination}")
    print("Speed thresholds (km/h)  " + " / ".join(map(speed_text, saved.speeds)))
    print(saved.dtc_status())
    print(f"CRC 0x{saved.crc:04X}. Readback verified.")


def run_gui(args):
    import tkinter as tk
    from tkinter import filedialog, font, messagebox, ttk

    root = tk.Tk()
    root.title(TITLE)
    if sys.platform == "win32":
        icon = Path(__file__).with_name("clippy.ico")
        if icon.is_file():
            root.iconbitmap(str(icon))
    root.columnconfigure(0, weight=1)
    frame = ttk.Frame(root, padding=16)
    frame.grid(sticky="ew")
    frame.columnconfigure(0, weight=1)
    source_path = dataset = None
    source_text = tk.StringVar(value="Select a J745 5M0907357F dataset XML")
    status = tk.StringVar()
    dtc_status = tk.StringVar()
    values = [tk.StringVar() for _ in FIELDS]
    entries = [tk.StringVar() for _ in FIELDS]
    widgets = []
    dtc_checks = {}

    def open_dataset(path):
        nonlocal source_path, dataset
        try:
            loaded = Dataset(path.read_bytes())
        except (OSError, ValueError) as exc:
            messagebox.showerror(TITLE, str(exc), parent=root)
            return
        source_path, dataset = path, loaded
        source_text.set(path.name)
        for current, entry, widget, raw in zip(values, entries, widgets, loaded.speeds):
            current.set(speed_text(raw))
            entry.set("")
            widget.state(["!disabled"])
        for event, (checked, checkbox) in dtc_checks.items():
            checked.set(event in loaded.dtc_slots)
            checkbox.state(["!disabled"])
        dtc_status.set(f"Input file  ·  {loaded.dtc_status()}")
        save_button.state(["!disabled"])
        suggested_button.state(["!disabled"])
        status.set(f"Input CRC 0x{loaded.crc:04X} verified. Blank fields keep current speeds.")
        widgets[0].focus_set()

    def browse():
        name = filedialog.askopenfilename(
            parent=root, title="Open Dataset XML", filetypes=[("Dataset XML", "*.xml")],
        )
        if name:
            open_dataset(Path(name))

    def save_as():
        if dataset is None:
            return
        suggested = args.output or next_output(source_path)
        name = filedialog.asksaveasfilename(
            parent=root, title="Save Dataset XML", initialdir=str(suggested.parent), initialfile=suggested.name,
            defaultextension=".xml", filetypes=[("Dataset XML", "*.xml")], confirmoverwrite=False,
        )
        if not name:
            return
        try:
            suppressed_dtcs = {event for event, (checked, _) in dtc_checks.items() if checked.get()}
            saved = dataset.save(Path(name), [entry.get() for entry in entries], suppressed_dtcs)
        except (OSError, ValueError) as exc:
            messagebox.showerror(TITLE, str(exc), parent=root)
            return
        status.set(f"Saved CRC 0x{saved.crc:04X}. Readback verified.")
        messagebox.showinfo(TITLE, f"Saved {Path(name).name}\n{saved.dtc_status()}\n{status.get()}", parent=root)

    def apply_suggested():
        if dataset is None:
            return
        suggested = SUGGESTED.copy()
        start, full, fixed = CURVE_AXIS
        fixed_speed = struct.unpack_from("<h", dataset.payload, fixed)[0]
        if fixed_speed < 2:
            del suggested[start], suggested[full]
        elif fixed_speed <= suggested[full]:
            span = suggested[full] - suggested[start]
            suggested[full] = fixed_speed - 1
            suggested[start] = max(0, suggested[full] - span)
        for (offset, _), entry in zip(FIELDS, entries):
            entry.set(speed_text(suggested[offset]) if offset in suggested else "")
        activation = speed_text(suggested[0x368])
        status.set(
            f"Suggested settings entered (DLA activation threshold {activation} km/h). "
            "Review them, then use Save As…"
        )

    ttk.Label(frame, textvariable=source_text, wraplength=390).grid(row=0, column=0, sticky="w")
    ttk.Button(frame, text="Open XML…", command=browse).grid(row=0, column=1, columnspan=2, sticky="e")
    ttk.Separator(frame).grid(row=1, column=0, columnspan=3, sticky="ew", pady=12)
    ttk.Label(frame, text="Current (km/h)").grid(row=2, column=1, padx=8)
    ttk.Label(frame, text="New (km/h)").grid(row=2, column=2)
    for row, ((_, label), current, entry) in enumerate(zip(FIELDS, values, entries), start=3):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Label(frame, textvariable=current).grid(row=row, column=1, padx=8)
        widget = ttk.Entry(frame, textvariable=entry, width=12, justify="right", state="disabled")
        widget.grid(row=row, column=2, sticky="e")
        widgets.append(widget)
    next_row = 3 + len(FIELDS)
    dtcs = ttk.LabelFrame(frame, text="Static cornering lights · Suppress DTC reporting", padding=8)
    dtcs.grid(row=next_row, column=0, columnspan=3, sticky="ew", pady=(12, 0))
    for column, (side, faults) in enumerate(CORNERING_DTC_GROUPS):
        dtcs.columnconfigure(column, weight=1)
        lamp = ttk.Frame(dtcs)
        lamp.grid(row=0, column=column, sticky="nw", padx=(0, 12))
        ttk.Label(lamp, text=side).grid(sticky="w", pady=(0, 4))
        for event, label in faults:
            checked = tk.BooleanVar(value=False)
            checkbox = ttk.Checkbutton(lamp, text=label, variable=checked, state="disabled")
            checkbox.grid(sticky="w", pady=2)
            dtc_checks[event] = checked, checkbox
    ttk.Label(dtcs, textvariable=dtc_status).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Label(frame, textvariable=status, wraplength=480).grid(
        row=next_row + 1, column=0, columnspan=3, sticky="w", pady=(10, 8),
    )
    suggested_button = ttk.Button(
        frame, text="Suggested settings", command=apply_suggested, state="disabled",
    )
    suggested_button.grid(row=next_row + 2, column=1, sticky="e", padx=8)
    save_button = ttk.Button(frame, text="Save As…", command=save_as, state="disabled")
    save_button.grid(row=next_row + 2, column=2, sticky="e")
    footer = ttk.Frame(frame)
    footer.grid(row=next_row + 3, column=0, columnspan=3, sticky="w", pady=(12, 0))
    default_font = font.nametofont("TkDefaultFont")
    free_font = default_font.copy()
    size = int(default_font.cget("size"))
    free_font.configure(size=size + (4 if size > 0 else -4), weight="bold")
    ttk.Label(footer, text=FREE_TEXT, foreground="#b00020", font=free_font).grid(
        row=0, column=0, sticky="w",
    )
    ttk.Label(footer, text=AUTHOR_TEXT).grid(row=0, column=1, sticky="w", padx=(4, 0))
    link_font = default_font.copy()
    link_font.configure(underline=True)
    support_link = ttk.Label(
        footer, text=SUPPORT_TEXT, foreground="#005a9c", font=link_font, cursor="hand2", takefocus=True,
    )
    support_link.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Label(footer, text="© 2026 lols11 · MIT AND Beerware").grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(4, 0),
    )

    def open_support(_event):
        webbrowser.open(SUPPORT_URL)

    for event in ("<Button-1>", "<Return>", "<space>"):
        support_link.bind(event, open_support)
    if args.xml:
        open_dataset(args.xml)
    root.mainloop()


def ensure_text_console():
    if sys.platform != "win32":
        return False
    if all(stream is not None for stream in (sys.stdin, sys.stdout, sys.stderr)):
        for stream in (sys.stdout, sys.stderr):
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8")
        return False
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    opened = not kernel.GetConsoleCP()
    if opened and not kernel.AllocConsole():
        raise ctypes.WinError(ctypes.get_last_error())
    for name, device, mode in (("stdin", "CONIN$", "r"), ("stdout", "CONOUT$", "w"), ("stderr", "CONOUT$", "w")):
        if getattr(sys, name) is None:
            setattr(sys, name, open(device, mode, encoding="utf-8", buffering=1))
    return opened


def main():
    argv = sys.argv[1:]
    options = argv[:argv.index("--")] if "--" in argv else argv
    text_options = {"-nogui", "--nogui", "-h", "--help", "--license"}
    opened_console = bool(text_options.intersection(options)) and ensure_text_console()
    parser = argparse.ArgumentParser(
        description=__doc__, epilog=CLI_BANNER, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("xml", nargs="?", type=Path, help="input dataset XML")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--gui", dest="gui", action="store_true", help="open the desktop editor")
    modes.add_argument("-nogui", "--nogui", dest="gui", action="store_false", help="use the text interface")
    parser.add_argument("--license", action="store_true", help="print the MIT and Beerware license texts")
    parser.set_defaults(gui=bool(getattr(sys, "frozen", False)))
    parser.add_argument("-o", "--output", type=Path, help="output path in text mode or suggested path in the GUI")
    parser.add_argument(
        "--cornering-dtc", choices=("suppress", "restore"),
        help="change all four cornering light DTCs and keep the speed settings in text mode",
    )
    try:
        args = parser.parse_args(argv)
        if args.license:
            print(LICENSE_TEXT, end="")
        elif args.gui:
            if args.cornering_dtc:
                parser.error("--cornering-dtc is available in text mode. In the GUI, use the DTC checkboxes.")
            run_gui(args)
        else:
            run_cli(args)
        return 0
    except (OSError, ValueError, EOFError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if opened_console:
            try:
                input("Press Enter to close…")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
