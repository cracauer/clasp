FROM clasp
MAINTAINER Christian Schafmeister <meister@temple.edu>

# install Jupyter and its dependencies; configure jupyter kernel
USER root
RUN apt-get update && apt-get -y install git-core \
  python2.7 python-pip python-dev ipython ipython-notebook
RUN pip install --upgrade pip && pip install jupyter
ADD tools/dockerfiles/jupyter/kernel.json \
  /home/app/.local/share/jupyter/kernels/lisp/kernel.json

# Overwrite the clasp-build clasp/Contents/Resources/source-code/extensions/cando/src/lisp directory
# with whatever new changes have been made in the hosts  extensions/cando/src/lisp/**   hierarchy
#    This is to refresh the Common Lisp code for Cando
ADD extensions/cando/src/lisp $HOME/clasp/Contents/Resources/source-code/extensions/cando/src/lisp

# set ownership and permissions before changing to app user
RUN chown -R app:app /home/app/.local $HOME/clasp/Contents/Resources/source-code/extensions/cando/src/lisp

# checkout quicklisp and its subprojects
USER app
RUN git clone --depth=1 https://github.com/quicklisp/quicklisp-client.git \
  $HOME/quicklisp
RUN mkdir $HOME/quicklisp/local-projects
RUN cd $HOME/quicklisp/local-projects \
 && git clone --depth=1 https://github.com/clasp-developers/usocket.git \
 && git clone --depth=1 https://github.com/clasp-developers/cl-jupyter.git \
 && git clone --depth=1 https://github.com/clasp-developers/bordeaux-threads.git \
 && git clone --depth=1 https://github.com/clasp-developers/cffi.git

# checkout slime
RUN git clone --depth=1 https://github.com/slime/slime $HOME/slime

RUN clasp -f "setup-cando"\
          -e '(load "/home/app/quicklisp/setup.lisp")'\
          -e "(ql:quickload :trivial-http)"\
          -e "(require :inet)"\
          -e '(setq core::*swank-home* "/home/app/slime")'\
          -e '(load (format nil "~a/swank-loader.lisp" core::*swank-home*))'\
          -e "(swank-loader:init :delete nil :reload nil :load-contribs nil)"\
          -e "(quit)"

RUN clasp -e '(load "/home/app/quicklisp/setup.lisp")'\
          -e "(ql:quickload :cl-jupyter)"\
          -e "(ql:quickload :pzmq)"\
          -e "(ql:quickload :cffi)"\
          -e "(ql:quickload :cffi-grovel)"\
          -e "(ql:quickload :nibbles)"\
          -e "(ql:quickload :ironclad)"\
          -e "(ql:quickload :uuid)"\
          -e "(ql:quickload :trivial-utf-8)"\
          -e "(quit)"

ADD tools/dockerfiles/examples /home/app/work/examples

ENTRYPOINT [ "jupyter", "notebook" ]
CMD        [ "--no-browser", "--ip=0.0.0.0", "--port=8888" ]