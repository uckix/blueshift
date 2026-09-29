#!/usr/bin/env python3
"""
Setup script for BlueShift.
"""

from setuptools import setup, find_packages
from pathlib import Path

this_dir = Path(__file__).parent
readme_path = this_dir / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

setup(
    name="blueshift",
    version="1.0.0",
    description="Bluetooth Low Energy KVM Switch for Linux",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="BlueShift Team",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "PyQt6>=6.4.0",
        "evdev>=1.6.0",
        "dbus-python>=1.2.18",
        "PyGObject>=3.42.0",
    ],
    entry_points={
        "console_scripts": [
            "blueshift = src.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: X11 Applications :: Qt",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Hardware :: Hardware Drivers",
    ],
)
