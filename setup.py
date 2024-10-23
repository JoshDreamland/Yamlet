from setuptools import setup, find_packages

at, g_mail = '@', 'gmail.com'
setup(
    name="yamlet",
    version="0.0.1.1",
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
