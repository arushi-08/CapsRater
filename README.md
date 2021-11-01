**CapsRater + FeatureCapture Model**


Introduction
------------
This repository contains an architecture for Automatic Essay Scoring systems that leverages Capsule Neural Networks, contextual BERT-based text representation, and key textually extracted features. This end-to-end pipeline captures semantics, coherence, and organizational structure along with fundamental rule-based features such as grammatical and spelling errors.


Installation
------------

Install Python 3.6

Install packages in requirements.txt

Launch BERT server using command:
```
 bert-serving-start -model_dir models/uncased_L-12_H-768_A-12/ -num_worker=5 -port 8190 -max_seq_len=NONE
```
 
Quickstart
```
 python ./main.py
```
