"""Windows 原生文件夹选择器（纯 ctypes，无第三方依赖）。

- pick_native_folders：原生多选文件夹（FOS_PICKFOLDERS | FOS_ALLOWMULTISELECT）
- pick_native_folder：原生单选文件夹

返回约定：
- pick_native_folders -> (used_native, paths)：paths 为 [] 表示取消，
  None 表示原生对话框已显示但结果处理出错（用 last_error() 查看原因）；
- pick_native_folder -> (used_native, path)：path 为 None 表示取消/出错。
- used_native=False：原生不可用/未显示，调用方应回退 Qt 对话框。

非 Windows 平台导入本模块保持可用（功能降级），不会报错。
"""
import ctypes
import os
import sys
import traceback
import uuid
from pathlib import Path

FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_ALLOWMULTISELECT = 0x00000200
FOS_NOCHANGEDIR = 0x00000008

SIGDN_FILESYSPATH = 0x80058000

S_OK = 0
ERROR_CANCELLED = 0x800704C7
CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 0x2

_CLSID_FILEOPENDIALOG = "DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7"
_IID_IFILEOPENDIALOG = "D57C7288-D4AD-4768-BE02-9D969532D960"
_IID_ISHELLITEM = "43826D1E-E718-42EE-BC55-A1E261C37BFE"
_IID_ISHELLITEMARRAY = "B63EA76D-1F85-456F-A19C-48159EFA858B"

# vtable 索引（已实测：与 Windows 真实 vtable 一致）
_VT_RELEASE = 2
_VT_SHOW = 3
_VT_SETOPTIONS = 9
_VT_SETFOLDER = 12
_VT_SETTITLE = 17
_VT_GETRESULT = 20          # IFileDialog::GetResult -> IShellItem（单选）
_VT_SETCLIENTGUID = 24      # IFileDialog::SetClientGuid（按 GUID 分开持久化“上次位置”）
_VT_GETRESULTS = 27         # IFileOpenDialog::GetResults -> IShellItemArray（多选）
_VT_ARR_GETCOUNT = 7        # IShellItemArray::GetCount
_VT_ARR_GETITEM = 8         # IShellItemArray::GetItemAt
_VT_ITEM_GETDISPLAYNAME = 5 # IShellItem::GetDisplayName

# 预告片/正片选择器各用独立 GUID，让 Windows 按 GUID 原生隔离各自的“上次位置”
_CLIENT_GUID_TRAILER = "6A3E2C1B-8F4D-4A5E-9B7C-2D1E0F3A4B5C"
_CLIENT_GUID_MOVIE = "B4C2D8E6-1A3F-4C5D-8E7F-9A0B1C2D3E4F"

try:
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
except AttributeError:
    ole32 = shell32 = user32 = None

_last_error = [None]


def last_error() -> str:
    return _last_error[0]


def _set_error(exc: Exception) -> None:
    _last_error[0] = f"{type(exc).__name__}: {exc}"
    try:
        log_path = Path.home() / ".trailermatch" / "native_picker.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            traceback.print_exc(file=f)
    except Exception:
        pass


def _guid(s: str):
    """把 GUID 字符串打包为 16 字节小端结构。"""
    return (ctypes.c_byte * 16)(*uuid.UUID(s).bytes_le)


class _ComObj:
    """COM 接口指针的薄封装：按 vtable 索引调用方法。"""

    def __init__(self, ptr):
        self.ptr = ptr
        self._vt = ctypes.cast(
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )

    def call(self, index: int, restype, *argspec):
        """argspec 为 (ctype, value) 交替；restype 用 c_uint 读取无符号 HRESULT。"""
        argtypes = [ctypes.c_void_p] + list(argspec[0::2])
        args = [self.ptr] + list(argspec[1::2])
        fn = ctypes.WINFUNCTYPE(restype, *argtypes)(self._vt[index])
        return fn(*args)

    def release(self):
        if self.ptr:
            self.call(_VT_RELEASE, ctypes.c_ulong)
            self.ptr = None


def _co_create():
    ptr = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        _guid(_CLSID_FILEOPENDIALOG),
        None,
        CLSCTX_INPROC_SERVER,
        _guid(_IID_IFILEOPENDIALOG),
        ctypes.byref(ptr),
    )
    if hr != S_OK or not ptr:
        return None
    return _ComObj(ptr)


def _shell_item_from_path(path: str):
    """从文件系统路径创建 IShellItem。"""
    item = ctypes.c_void_p()
    hr = shell32.SHCreateItemFromParsingName(
        ctypes.c_wchar_p(path), None, _guid(_IID_ISHELLITEM), ctypes.byref(item)
    )
    if hr != S_OK or not item:
        return None
    return _ComObj(item)


def _shell_item_path(item: _ComObj) -> str or None:
    name_ptr = ctypes.c_wchar_p()
    fn = ctypes.WINFUNCTYPE(
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_wchar_p),
    )(item._vt[_VT_ITEM_GETDISPLAYNAME])
    hr = fn(item.ptr, SIGDN_FILESYSPATH, ctypes.byref(name_ptr))
    if hr != S_OK or not name_ptr.value:
        return None
    path = name_ptr.value
    ole32.CoTaskMemFree(ctypes.cast(name_ptr, ctypes.c_void_p))
    return path


def _collect_results(dialog: _ComObj) -> list:
    """从已确认的多选对话框中取回选中文件夹路径列表。"""
    arr_ptr = ctypes.c_void_p()
    hr = dialog.call(
        _VT_GETRESULTS,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.byref(arr_ptr),
    )
    if hr != S_OK or not arr_ptr:
        return []

    arr = _ComObj(arr_ptr)
    try:
        count = ctypes.c_uint(0)
        arr.call(
            _VT_ARR_GETCOUNT,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.byref(count),
        )
        paths = []
        for i in range(count.value):
            item_ptr = ctypes.c_void_p()
            hr = arr.call(
                _VT_ARR_GETITEM,
                ctypes.c_uint,
                ctypes.c_uint,
                i,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.byref(item_ptr),
            )
            if hr != S_OK or not item_ptr:
                continue
            item = _ComObj(item_ptr)
            try:
                p = _shell_item_path(item)
                if p:
                    paths.append(p)
            finally:
                item.release()
        return paths
    finally:
        arr.release()


def _show_dialog(parent, title: str, extra_options: int, start_dir: str, client_guid: str = None):
    """创建并显示原生文件夹对话框。

    start_dir 有效时用 SetFolder 强制定位；否则交由 Windows 按该 GUID 记忆的位置打开。
    返回 (status, dialog)：'ok'/'cancel'/'fail'。
    """
    dialog = _co_create()
    if dialog is None:
        return "fail", None
    try:
        if client_guid:
            guid = _guid(client_guid)
            dialog.call(
                _VT_SETCLIENTGUID,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.addressof(guid),
            )
        dialog.call(_VT_SETTITLE, ctypes.c_uint, ctypes.c_wchar_p, title)
        dialog.call(
            _VT_SETOPTIONS,
            ctypes.c_uint,
            ctypes.c_uint,
            FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_NOCHANGEDIR | extra_options,
        )
        if start_dir and os.path.isdir(start_dir):
            start_item = _shell_item_from_path(start_dir)
            if start_item is not None:
                dialog.call(_VT_SETFOLDER, ctypes.c_uint, ctypes.c_void_p, start_item.ptr)
                start_item.release()
        hwnd = (
            ctypes.c_void_p(int(parent.winId()))
            if parent is not None
            else ctypes.c_void_p(user32.GetForegroundWindow())
        )
        hr = dialog.call(_VT_SHOW, ctypes.c_uint, ctypes.c_void_p, hwnd)
        if hr == ERROR_CANCELLED:
            dialog.release()
            return "cancel", None
        if hr != S_OK:
            dialog.release()
            return "fail", None
        return "ok", dialog
    except Exception:
        dialog.release()
        raise


def pick_native_folders(parent=None, title="选择文件夹", start_dir=None):
    """弹出原生文件夹多选对话框。返回 (used_native, paths)。"""
    if sys.platform != "win32" or ole32 is None:
        return False, []
    _last_error[0] = None

    shown = False
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        status, dialog = _show_dialog(
            parent, title, FOS_ALLOWMULTISELECT, start_dir, _CLIENT_GUID_TRAILER
        )
        if status != "ok":
            # cancel -> (True, []); fail -> (False, []) 允许回退 Qt
            return status == "cancel", []
        shown = True
        try:
            return True, _collect_results(dialog)
        finally:
            dialog.release()
    except Exception as exc:
        _set_error(exc)
        return shown, None
    finally:
        ole32.CoUninitialize()


def pick_native_folder(parent=None, title="选择文件夹", start_dir=None):
    """弹出原生单选文件夹对话框。返回 (used_native, path)。"""
    if sys.platform != "win32" or ole32 is None:
        return False, None
    _last_error[0] = None

    shown = False
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        status, dialog = _show_dialog(
            parent, title, 0, start_dir, _CLIENT_GUID_MOVIE
        )
        if status != "ok":
            # cancel -> (True, None); fail -> (False, None) 允许回退 Qt
            return status == "cancel", None
        shown = True
        try:
            result_ptr = ctypes.c_void_p()
            hr = dialog.call(
                _VT_GETRESULT,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.byref(result_ptr),
            )
            if hr != S_OK or not result_ptr:
                return True, None
            item = _ComObj(result_ptr)
            try:
                return True, _shell_item_path(item)
            finally:
                item.release()
        finally:
            dialog.release()
    except Exception as exc:
        _set_error(exc)
        return shown, None
    finally:
        ole32.CoUninitialize()
