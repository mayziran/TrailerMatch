"""版本号读取。

发布版本由 CI 在构建时从 git tag 写入 core/_version.py；
本地源码运行未注入时回退为 dev，无需手动维护版本号。
"""


def get_version() -> str:
    try:
        from ._version import __version__
        return __version__
    except ImportError:
        return "dev"
