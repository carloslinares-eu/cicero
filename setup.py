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
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU GPLv3",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)
