#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open("README.md") as readme_file:
    readme = readme_file.read()

requirements = [
    "dbus-next>=0.1.4;sys_platform=='linux'",
    "rubicon-objc>=0.3.1;sys_platform=='darwin'",
]

dev_requires = [
    "black",
    "bump2version",
    "flake8",
    "mypy",
    "pre-commit",
    "pytest",
    "pytest-cov",
]

docs_require = [
    "sphinx",
    "m2r2",
    "sphinx-autoapi",
    "sphinx_rtd_theme",
]

setup(
    author="Sam Schott",
    author_email="sam.schott@outlook.com",
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    description="Python library for cross-platform desktop notifications",
    setup_requires=["wheel"],
    install_requires=requirements,
    extras_require={
        "dev": dev_requires,
        "docs": docs_require,
    },
    license="MIT license",
    long_description=readme,
    include_package_data=True,
    keywords="desktop-notifier",
    name="desktop-notifier",
    packages=find_packages("src"),
    package_dir={"": "src"},
    url="https://github.com/samschott/desktop-notifier",
    version="1.0.0",
    zip_safe=False,
)
