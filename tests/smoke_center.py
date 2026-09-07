import importlib.util, os, sys, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
scratch = pathlib.Path(sys.argv[2]); scratch.mkdir(parents=True, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = str(scratch)
conf = scratch / "tabprec.conf"
conf.write_text("SCALE=0.2900\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\n")
spec = importlib.util.spec_from_file_location("wc", sys.argv[1])
wc = importlib.util.module_from_spec(spec); spec.loader.exec_module(wc)
from PyQt6.QtWidgets import QApplication
app = QApplication([])
args = [1.5135] if "aspect" in wc.PrecisionTab.__init__.__code__.co_varnames else []
tab = wc.PrecisionTab(*args)
for name, box in (("hold", tab.hold), ("long press", tab.long_press)):
    print(f"{name} shown: {box.value()} | text: {box.text()} | range: {box.minimum()} {box.maximum()}")
tab.hold.setValue(0.05)                  # below the old 0.3 floor: must stick
tab.long_press.setValue(0.0)
print("conf after hold 0.05, long 0:", conf.read_text().replace("\n", " | "))
