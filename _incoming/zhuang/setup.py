from setuptools import setup, find_packages

setup(
    name="zhuang_system",
    version="0.1.0",
    packages=find_packages(exclude=["tests*", "scripts*"]),
    python_requires=">=3.10",
    install_requires=[
        "akshare>=1.14.0",
        "numpy>=1.24.0",
        "pandas>=2.0.0",
        "pyyaml>=6.0",
    ],
)
