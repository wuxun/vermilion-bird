"""PyInstaller runtime hook: 预加载 tiktoken 编码文件。

tiktoken 通过 pkgutil 扫描 tiktoken_ext 命名空间包发现编码构造器。
PyInstaller 打包后命名空间包的 iter_modules 可能失效，
此 hook 显式导入插件模块，确保编码在 get_encoding() 调用前已注册。
"""
import tiktoken_ext.openai_public  # noqa: F401 注册 ENCODING_CONSTRUCTORS
