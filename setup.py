from setuptools import setup, find_packages
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8") if (this_directory / "README.md").exists() else ""

setup(
    name="nseuniverse",
    version="1.0.0",
    description="Institutional Point-in-Time Python Client for the Entire National Stock Exchange (NSE) Universe",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="sweeza",
    url="https://github.com/sweeza/NSE-PIT-Universe",
    packages=find_packages(include=["nseuniverse", "nseuniverse.*"]),
    python_requires=">=3.9",
    install_requires=[
        "pandas>=1.3.0",
        "numpy>=1.20.0",
        "pyarrow>=7.0.0",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Topic :: Office/Business :: Financial :: Investment",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Operating System :: OS Independent",
    ],
    keywords="nse quantitative-finance algorithmic-trading backtesting point-in-time nifty stocks market-data",
)
