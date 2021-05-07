import setuptools


with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="cicero",
    version="0.1",
    author="Carlos Linares",
    author_email="contact@carloslinares.eu",
    description="Powerpoint Translation Tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/carloslinares-eu/cicero",
    packages=["cicero"],
    package_data={"cicero": ['./*.ico']},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU GPLv3",
        "Operating System :: OS Independent",
    ],
    install_requires=[
            "google.oauth2", "google.cloud.translate_v2", "google.auth", "pptx", "tkinter", "tkinter.ttk", "xlsxwriter"
        ],
    entry_points={"console_scripts": ["cicero=cicero.__main__:main"]},
    python_requires='>=3.8',
)
