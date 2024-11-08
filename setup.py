import re
from pathlib import Path
from setuptools import setup, find_packages

def get_version():
  version_file = Path(__file__).parent / "yamlet.py"
  with version_file.open() as f:
    version_match = re.search(r'^VERSION = ["\']([^"\']+)["\']', f.read(), re.M)
    if version_match:
      return version_match.group(1)
    raise RuntimeError("Unable to find version string.")

yamlet_version = get_version()
print(f'Setting up Yamlet version {yamlet_version}')

at, g_mail = '@', 'gmail.com'
setup(
    name="yamlet",
    version=yamlet_version,
    author="Josh Ventura",
    author_email=f"JoshV{10}{at}{g_mail}",
    description="A GCL-like templating engine for YAML",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="https://github.com/JoshDreamland/Yamlet",
    py_modules=["yamlet"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    install_requires=[
        'ruamel.yaml>=0.17.0',
    ],
)
