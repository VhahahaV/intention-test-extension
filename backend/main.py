import json
import os
import re
import shutil
from tqdm import tqdm
from generator import IntentionTest as IntentionTestGenerator
from generator_no_reference import RAGTesterNoReference as IntentionTestGeneratorNoReference

from configs import Configs
from server import ModelQuerySession
from retriever import Retriever
from knowledge_graph_constructor import construct_knowledge_graph
import pathlib
from extension_api.collect_pairs.main import dump_collect_pairs

import logging
logger = logging.getLogger(__name__)

import sys
logger.warning('UTF-8 mode is enabled' if sys.flags.utf8_mode else 'UTF-8 mode is not enabled and I/O error may occur')

# WARNING remember to replace the built-in open() to use UTF-8
# because project file should be opened using UTF-8, but subprocess.run() (for Java, but CodeQL should still use UTF-8) output should still be decoded in local encoding
# both would cause error if not set properly

class IntentionTest:
    def __init__(self, project_path, configs, use_reference = True):
        self.project_path = project_path
        self.corpus = None
        self.retriever = None
        self.top_k_references = 1

        self.corpus_path =  configs.corpus_path
        self.generator = IntentionTestGenerator(configs) if use_reference else IntentionTestGeneratorNoReference(configs)

    def load_corpus(self):
        # collect pairs
        assert os.path.exists(self.corpus_path)
        with open(self.corpus_path, 'r', encoding='utf8') as f:
            all_data = json.load(f)

        corpus_fm, corpus_fm_name, corpus_tc, corpus_tc_name, corpus_test_case_path = [], [], [], [], []

        for each_data in all_data:
            corpus_fm.append(''.join(each_data['focal_method']))
            corpus_fm_name.append(each_data['focal_method_name'])
            corpus_tc.append(''.join(each_data['full_test_content']))
            corpus_tc_name.append(each_data['test_name'].split('::::')[-1].split('(')[0])
            corpus_test_case_path.append(each_data['test_path'])

        self.corpus = {
            'corpus_fm': corpus_fm, 
            'corpus_fm_name': corpus_fm_name, 
            'corpus_tc': corpus_tc, 
            'corpus_tc_name': corpus_tc_name, 
            'corpus_test_case_path': corpus_test_case_path
            }

    def prepare_retriever(self):
        assert self.corpus is not None
        self.retriever = Retriever(
            corpus_fm=self.corpus['corpus_fm'], 
            corpus_fm_name=self.corpus['corpus_fm_name'], 
            corpus_tc=self.corpus['corpus_tc'], 
            corpus_tc_name=self.corpus['corpus_tc_name'], 
            corpus_test_case_path=self.corpus['corpus_test_case_path']
            )

    def retrieve_reference(self, target_focal_method, target_test_case_name):
        assert self.retriever is not None
        references_fm_rag, references_fm_name_rag, references_tc_rag, reference_tc_name_rag, references_score, references_tc_path = self.retriever.retrieve_v2(target_fm=target_focal_method, target_tc_name=target_test_case_name, top_k=self.top_k_references)

        focal_method_name = target_focal_method.split('\n')[0].split('(')[0].split()[-1]  # TODO it would be better to use the method signature
        
        assert self.top_k_references == 1  
        top_1_reference_fm_name = references_fm_name_rag[0]

        # TODD: remove the following and use the full method signature
        top_1_reference_fm_name = top_1_reference_fm_name.split('::::')[1].split('(')[0]
        #

        if top_1_reference_fm_name == focal_method_name:
            top_1_reference_fm_rag = None
        else:
            top_1_reference_fm_rag = references_fm_rag[0]
        
        top_1_reference_tc_rag = references_tc_rag[0]
        top_1_reference_tc_path = references_tc_path[0]
        top_1_reference_tc_name = reference_tc_name_rag[0]
        
        return top_1_reference_fm_rag, top_1_reference_tc_rag, top_1_reference_tc_path, top_1_reference_tc_name

def main(target_focal_method, target_focal_file, target_test_case_name, project_path, focal_file_path, query_session: ModelQuerySession | None = None):
    # project_name = project_path.split('/')[-1]     not compatible with Windows path
    project_name = pathlib.Path(project_path).stem
    # replace the disk letter to upper case to match CodeQL path 
    tester_path = re.sub(r'[a-z]:/', lambda s: s[0].upper(), pathlib.Path(__file__).parent.absolute().as_posix())
    configs = Configs(project_name, tester_path)

    intention_test = IntentionTest(project_path, configs)
    
    if not isinstance(intention_test.generator, IntentionTestGenerator):
        raise ValueError('RAGTesterNoReference is not supported yet')

    # Connect to query session
    intention_test.generator.connect_to_request_session(query_session)

    # Showing the system prompt early here
    messages = intention_test.generator.prepend_system_prompt()

    intention_test.load_corpus()
    intention_test.prepare_retriever()

    logger.info('Checking test-focal corpus file')
    # prepare test-focal pairs
    if not configs.is_corpus_prepared():
        logger.warning('The test-focal corpus file does not exists, start collecting pairs')
        dump_collect_pairs(project_path)

    # prepare two copies of the project in repos_with_test and repos_removing_test. the former is used to create the initial codeql database, while the latter is used to wirte the referable and generated test case during the generation process.
    shutil.copytree(project_path, configs.project_with_test_file_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))
    shutil.copytree(project_path, configs.project_without_test_file_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))

    # /intention_test_extension/data/repos_removing_test/spark/src/test/java/spark/embeddedserver/jetty/EmbeddedJettyFactoryTest.java
    project_without_test_file_dir = os.path.dirname(configs.project_without_test_file_path)

    # focal_file_path = f"{project_without_test_file_dir}/{focal_file_path[focal_file_path.index(project_name):]}" 
    # TODO fix all path incompatibility
    focal_file_path = (pathlib.Path(project_without_test_file_dir) / focal_file_path[focal_file_path.index(project_name):]).as_posix()
    target_test_case_path = focal_file_path.replace('src/main/java', 'src/test/java').replace('.java', 'Test.java')

    # create codeql database for repos_with_test
    logger.info('Creating codeql database and constructing knowledge graph for project')
    is_success = construct_knowledge_graph(configs)
    if not is_success:
        logger.info('Cannot construct knowledge graph for project')
        raise ValueError('construct knowledge graph failed')

    logger.info('Retrieving reference test case')
    top_1_reference_fm_rag, top_1_reference_tc_rag, top_1_reference_tc_path, top_1_reference_tc_name = intention_test.retrieve_reference(target_focal_method, target_test_case_name)

    # because the codeql database created during generating is based on repos_removing_test. the referable and generated test case will written in repose_removing_test dir to create the database and analyze.
    top_1_reference_tc_path = f"{project_without_test_file_dir}/{top_1_reference_tc_path[top_1_reference_tc_path.index(project_name):]}"

    logger.info('Starting a multi-round chat for generating test case')
    messages, generated_test_case, str_for_is_referable, fail_type = intention_test.generator.generate_test_case(
        target_focal_method=target_focal_method, 
        target_focal_file=target_focal_file, 
        target_test_case_name=target_test_case_name, 
        referable_test_case=top_1_reference_tc_rag, 
        referable_focal_method=top_1_reference_fm_rag, 
        target_test_case_path=target_test_case_path,
        target_focal_file_abs_path=focal_file_path,
        referable_tc_class_name=top_1_reference_tc_path.split('/')[-1].split('.')[0], 
        referable_tc_method_name=top_1_reference_tc_name,
        referable_test_case_path=top_1_reference_tc_path,
        messages=messages
    )

    if str_for_is_referable != 'not_referable':
        return messages, generated_test_case
    
    query_session.write_noref_message()

    intention_test_no_ref = IntentionTest(project_path, configs, False)
    intention_test_no_ref.load_corpus()
    intention_test_no_ref.prepare_retriever()

    messages, generated_test_case, str_for_is_referable, fail_type = intention_test_no_ref.generator.generate_test_case(
        target_focal_method=target_focal_method, 
        target_focal_file=target_focal_file, 
        target_test_case_name=target_test_case_name, 
        referable_test_case="", 
        referable_focal_method="", 
        target_test_case_path=target_test_case_path,
        target_focal_file_abs_path=focal_file_path,
        referable_tc_class_name="", 
        referable_tc_method_name="",
        referable_test_case_path="",
        query_session=query_session
    )
    
    return messages, generated_test_case
