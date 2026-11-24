# VW PQ J745 AFS / DLA Dataset Editor

Edit XML datasets for the J745 headlamp control module on VW PQ-platform AFS and Dynamic Light Assist (DLA) systems. The repository includes the desktop editor and a Python CLI.

> [!CAUTION]
> **Off-road use only.** Use this tool on a bench or a vehicle operated exclusively off public roads.
>
> The software is provided as is, without warranty. The author accepts no responsibility for its use or any consequences.

> [!WARNING]
> Uploading a dataset to J745 clears the module coding and invalidates the headlamp basic setting. Back up the original dataset if possible and coding before uploading. Restore the correct coding, run and acknowledge the headlamp basic setting, then verify alignment and check for faults.

## Compatibility

The editor targets **J745 at address 55, SW `5M0 907 357 F / 0111`**. Confirm the module and software before use. The XML editor checks the diagnostic address, block number, internal header, block length and CRC. It accepts custom or missing `ZDC_NAME` and `ZDC_VERSION` metadata, which is preserved as supplied.

The editor saves a new XML file. Use a separate diagnostic tool for parameterization.

## Downloads

- **Linux CLI** ([`dla_dataset_editor.py`](https://github.com/lols11/PQ-J754-AFS-DLA-dataset-editor/releases/latest/download/dla_dataset_editor.py)). Run `python3 dla_dataset_editor.py original.xml` with Python 3.8 or newer. The editor prints its banner, compatibility information and warnings before opening the input.
- **Windows x64** ([`DLA-Dataset-Editor-Windows-x64.exe`](https://github.com/lols11/PQ-J754-AFS-DLA-dataset-editor/releases/latest/download/DLA-Dataset-Editor-Windows-x64.exe)). Run the standalone EXE to open the desktop editor. Pass `-nogui` for text mode.

## Edit an XML dataset in the GUI

To open the GUI from the Python script, install Tkinter and run `python3 dla_dataset_editor.py --gui`.

1. Open the XML dataset from your module.
2. Enter only the speeds you want to change. Blank fields retain their original values.
3. Use the four cornering-light checkboxes if required. Checked suppresses reporting for the corresponding DTC. Unchecked restores its reporting.
4. Select **Save As** and use a new output filename. The editor recalculates the CRC and verifies the saved file by reopening it.

### Speed settings

See [DLA speed settings](README_VALUES.md) for all editable values and both beam modes.

| Setting | Effect | Factory application example |
| --- | --- | --- |
| DLA activation speed | Minimum speed to enter the selective DLA mode when the other conditions are met | 60 km/h |
| DLA off speed (either lamp outside full high beam) | Speed below which active DLA stops when either headlamp is outside the full-high-beam range | 55 km/h |
| DLA off speed (both lamps at full high beam) | Speed below which active DLA stops when both headlamps are in the full-high-beam range | 30 km/h |
| Street lighting inhibit speed | A qualifying street-lighting signal from the camera can start an inhibit below this speed | 85 km/h |

For example, with DLA active at 50 km/h, both headlamps at full high beam allow it to stay active. When either beam moves outside the full-high-beam range, the 55 km/h threshold applies and DLA stops. Re-entry requires the activation threshold again. A street-lighting inhibit that is already active remains in effect while the camera reports the qualifying lighting status. It clears after the signal drops and the release delay expires.

### Cornering-light DTCs

| Bulb | Short to ground | Open circuit |
| --- | --- | --- |
| Left | `C1083 11` | `C1083 13` |
| Right | `C1084 11` | `C1084 13` |

The editor changes the selected J745 event entries and preserves unrelated entries. The lamp modules continue to diagnose their outputs. Existing fault history may need to be cleared separately with a diagnostic tester.

### Command line

```sh
python3 dla_dataset_editor.py original.xml -o edited.xml
python3 dla_dataset_editor.py original.xml --cornering-dtc suppress -o suppressed.xml
python3 dla_dataset_editor.py suppressed.xml --cornering-dtc restore -o restored.xml
```

Text mode prompts for the speed settings. The bulk `suppress` and `restore` commands affect all four cornering-light DTCs and keep the speeds. Use the GUI for individual selections.

For dataset capture over CCP, see the [CCP README](README_CCP.md).

## Build the Windows EXE

Run on Windows with x64 Python and Tkinter installed.

```powershell
py -m pip install pyinstaller
py -m PyInstaller --onefile --windowed --noupx --name "DLA Dataset Editor" dla_dataset_editor.py
```

The executable is in `dist`. Python and the EXE use the same editor code.

**FREE FOR ALL. BY LOLS11.** [Support me or check out my work](https://linktr.ee/lols11)

[MIT License](LICENSE)
