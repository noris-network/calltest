from setuptools import setup, find_packages

LONG_DESC = open("README.rst").read()

setup(
    name="calltest",
    use_scm_version={"version_scheme": "guess-next-dev", "local_scheme": "dirty-tag"},
    description="A distributed phone call test program",
    url="https://github.com/smurfix/calltest",
    long_description=LONG_DESC,
    author="Matthias Urlichs",
    author_email="matthias@urlichs.de",
    license="proprietary",
    packages=find_packages(),
    setup_requires=["setuptools_scm", "pytest_runner"],
    install_requires=[
        "asyncclick",
        "asyncari >= 0.7.3",
        "trio >= 0.11",
        "range_set >= 0.2",
        "attrs >= 18.2",
        "jsonschema >= 2.5",
        "pyyaml >= 3",
    ],
    tests_require=[
        "pytest",
        "pytest-trio",
        "flake8 >= 3.7"
    ],
    keywords=["async", "asterisk"],
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Information Technology",
        "Framework :: AsyncIO",
        "Framework :: Trio",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: Implementation :: CPython",
    ],
    entry_points="""
    [console_scripts]
    calltest = calltest.command:cmd
    """,
    zip_safe=True,
)
