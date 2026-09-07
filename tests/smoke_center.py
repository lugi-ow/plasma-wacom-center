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
print("hold shown:", tab.hold.value(), "| text:", tab.hold.text(), "| range:", tab.hold.minimum(), tab.hold.maximum())
tab.hold.setValue(0.8)
print("conf after setting 0.8:", conf.read_text().replace("\n", " | "))
