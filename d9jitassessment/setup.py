from setuptools import find_packages, setup


setup(name='d9jitassessment',
      version='0.1',
      description='Checkpoint CloudGuard Dome9 Just In Time Assessment Execution',
      url='',
      author='Idan Perez',
      author_email='',
      packages=find_packages(),
      install_requires=['boto3','requests'],
      include_package_data=True,
      zip_safe=False)