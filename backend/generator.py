import argparse
import json
import re
import sys
import os
import subprocess
import shutil
from server import ModelQuerySession
from openai import OpenAI
from tqdm import tqdm
from configs import Configs
from test_case_runner import TestCaseRunner
from user_config import global_config

import logging
logger = logging.getLogger(__name__)

CODEQL_PATH = global_config['tools']['codeql']

class IntentionTest:
    def __init__(self, configs, max_round=5):
        super().__init__()
        self.configs = configs
        self.test_case_runner = TestCaseRunner(configs, configs.test_case_running_log_dir)
        api_key = ""
        api_key = configs.openai_api_key
        
        client = Client(
            api_key=api_key, 
            max_query_round=3, 
            knowledge_graph_path=configs.knowledge_graph_save_path, 
            method_invocation_in_a_method_table_path=configs.method_invocation_in_a_method_table_save_path,
            method_invocation_in_a_file_table_path=configs.method_invocation_in_a_file_table_save_path,
            codeql_database_for_project_path=configs.codeql_database_for_project_path, 
            codeql_database_for_target_tc_path=configs.codeql_database_for_target_tc_path,
            query_method_invocation_in_a_file_template_path=configs.query_method_invocation_in_a_file_template_path, 
            query_method_invocation_in_a_file_impl_path = configs.query_method_invocation_in_a_file_impl_path,
            project_without_test_file_path=configs.project_without_test_file_path,
            prompt_message_callback = self.save_messages
            )
        self.client = client
        self.analyzer = Analyzer(client)
        self.generator = Generator(client)
        self.max_round = max_round  # the maximum number of rounds for modification (without the first generation)
        self.system_prompt = """You are an expert in Junit test case generation. I will give you a target focal method and relevant information. Your task is to generate a target test case with a specified name for a given target focal method. I will guide you to complete the task step by step. Please strictly follow my each instruction."""

        self.log_dir = configs.generation_log_dir
        os.makedirs(self.log_dir, exist_ok=True)

        self.query_method_invocation_in_a_file_template_path = configs.query_method_invocation_in_a_file_template_path
        self.query_method_invocation_in_a_file_impl_path = self.query_method_invocation_in_a_file_template_path.replace('_template', f'_impl_{configs.project_name}')
        self.query_constructor_invocation_in_a_file_template_path = configs.codeql_analyze_constructor_invocation_in_a_file_template_path
        self.query_constructor_invocation_in_a_file_impl_path = self.query_constructor_invocation_in_a_file_template_path.replace('_template', f'_impl_{configs.project_name}')
        self.query_variable_declaration_in_a_file_template_path = configs.query_variable_declaration_in_a_file_template_path
        self.query_variable_declaration_in_a_file_impl_path = self.query_variable_declaration_in_a_file_template_path.replace('_template', f'_impl_{configs.project_name}')

        # overload_relation_dict: method_name -> [class_name -> method_A_signatures]
        with open(configs.full_method_invocation_dict_save_path, 'r', encoding='utf8') as f:
            self.overload_relation_dict = json.load(f)

        # parameter_relation_dict: class::::method_A_sign -> [the methods that use the method_A as parameter]
        self.parameter_relation_dict = self.get_parameter_relation_dict(self.overload_relation_dict)

        # call_relation_dict: class::::method_A_sign -> [the methods called by method_A]
        with open(configs.method_invocation_in_a_method_table_save_path, 'r', encoding='utf8') as f:
            method_invocation_in_a_method_table = json.load(f)
        self.call_relation_dict = self.get_call_relation_dict(method_invocation_in_a_method_table)

        # define_relation_dict: class_name -> [the methods within class_name]
        with open(configs.method_declaration_save_path, 'r', encoding='utf8') as f:
            method_declaration = json.load(f)
        self.define_relation_dict = self.get_define_relation_dict(method_declaration)

    def connect_to_request_session(self, query_session: ModelQuerySession):
        self.query_session = query_session

    def prepend_system_prompt(self):
        messages = [{"role": "system", "content": self.system_prompt}]
        self.save_messages(messages)
        return messages

    def generate_test_case(self, target_focal_method, target_focal_file, target_test_case_name, referable_test_case, referable_focal_method, target_test_case_path, target_focal_file_abs_path, referable_tc_class_name, referable_tc_method_name, referable_test_case_path, messages = []):
        success_gen = False
        generated_test_case = None

        # add line number for code
        target_focal_method = self.add_line_number_for_code(target_focal_method)
        target_focal_file = self.add_line_number_for_code(target_focal_file)
        referable_test_case = self.add_line_number_for_code(referable_test_case)
        referable_focal_method = self.add_line_number_for_code(referable_focal_method) if referable_focal_method is not None else None
        
        # determine referable
        messages_determine = self.analyzer.determine_reference(target_focal_method, target_test_case_name, referable_test_case, referable_focal_method, messages)
        is_referable, not_referable = False, False
        if "YES, REFERABLE" in messages_determine[-1]["content"]:
            is_referable = True
        if "NO, NOT REFERABLE" in messages_determine[-1]["content"]:
            not_referable = True
        
        if not is_referable ^ not_referable:
            logger.error("\n[Error] conflict in determining referable.\n")
            return messages_determine, generated_test_case, "conflict", None
        
        if not_referable:  # will generate without reference (in ablation study)
            return messages_determine, generated_test_case, "not_referable", None

        self.client.query.method_invocation_in_focal_file = None
        self.client.query.method_invocation_in_referable_tc = None
        
        # get the InitInvoDict on the referable test case
        rtc = self.remove_line_number_for_code(referable_test_case)
        all_init_invocation_nodes, init_method_node, init_constructor_node, init_variable_node = self.get_invocation_in_a_test_case(referable_test_case_path, rtc)
        assert len(all_init_invocation_nodes) > 0 and len(init_variable_node) > 0
        #

        # start generation
        for round_i in range(self.max_round + 1):
            # Generate
            if round_i == 0:
                # messages = self.analyzer.analyze_intention(target_focal_method, target_focal_file, target_test_case_name, referable_test_case, referable_focal_method, messages)

                # messages = self.generator.make_first_modification(
                #     messages, target_test_case_path, target_focal_file_abs_path, referable_tc_class_name, referable_tc_method_name
                # )
                
                # NOTE Here we did not use messages_determine! The 2 determine messages were omitted from the history.
                messages = self.analyzer.do_not_analyze_skip_to_modification(target_focal_method, target_focal_file, target_test_case_name, referable_test_case, referable_focal_method, messages)
            else:
                # get the GenInvoDict on the generated test case
                all_gen_invocation_nodes, gen_method_node, gen_constructor_node, gen_variable_node = self.get_invocation_in_a_test_case(target_test_case_path, generated_test_case)

                if all_gen_invocation_nodes is not None:
                    # explore the knowledge graph
                    additional_method_overload, additional_constructor_overload, \
                        additional_method_parameter, additional_constructor_parameter, \
                            additional_callee_methods, additional_callee_constructors, \
                                additional_define_methods, additional_define_constructors = self.explore_knowledge_graph(gen_method_node, gen_constructor_node)  # TODO: consider explore new nodes which use the variable_node as parameter.

                    # rank the additional invocation
                    invocation_node_added_by_gen = list(set(all_gen_invocation_nodes) - set(all_init_invocation_nodes))
                    variable_node_added_by_gen = list(set(gen_variable_node) - set(init_variable_node))
                    top_additional_nodes, top_additional_node_scores = self.rank_additional_invocation(all_gen_invocation_nodes, 
                                                                                                          gen_variable_node, 
                                                                                                          invocation_node_added_by_gen,
                                                                                                        variable_node_added_by_gen,
                                                                                                        additional_method_overload, additional_constructor_overload, 
                                                                                                        additional_method_parameter, additional_constructor_parameter, 
                                                                                                        additional_callee_methods, additional_callee_constructors, 
                                                                                                        additional_define_methods, additional_define_constructors,
                                                                                                        top_k=3)
                else:
                    top_additional_nodes, top_additional_node_scores = [], []
                messages = self.generator.make_modification(messages, fail_type, target_test_case_path, target_focal_file_abs_path, referable_tc_class_name, referable_tc_method_name, top_additional_nodes)
            
            # Run test case
            generated_test_case = self.extract_target_tc(messages)
            # TEST check
            if generated_test_case.split('\n')[0].startswith('1'):
                # print()
                raise ValueError('generated test case should not contain line number')
            error_msg, fail_type = self.process_and_run_test_case(generated_test_case, target_test_case_path)

            # Analyze running result NOTE the error_msg could be incomplete here due to Maven (may add ... to overflowing end)
            if error_msg is None:
                messages = self.analyzer.final_check(messages)
            else:
                messages = self.analyzer.analyze_error_msg(error_msg, messages)

            # Check if generation is successful
            if error_msg is None and "FINISH GENERATION" in messages[-1]["content"]:
                success_gen = True
                break
            elif error_msg is None and "FINISH GENERATION" not in messages[-1]["content"]:
                logger.warning('generation does not align with the intention')
        
        if os.path.exists(target_test_case_path):
            os.remove(target_test_case_path)

        # # TEST
        # with open(f'{self.log_dir}/{self.configs.project_name}_messages_log.txt', 'w', encoding='utf8') as f:
        #     for each in messages:
        #         f.write(f"==={each['role']}===\n{each['content']}\n\n")
        
        if success_gen:
            logger.info('Test case generation successfully.\n')
        else:
            logger.info('Test case generation failed.\n')
        #

        return messages, generated_test_case, 'referable', fail_type

    def update_messages_to_remote(self, messages):
        # TODO notify front-end for messages, maybe trasmit full (instead of transmit update only)?
        if self.query_session:
            self.query_session.update_messages(messages)

    def save_messages(self, messages):
        logger.info(f"Sending and saving messages:\n{json.dumps(messages, indent=4)}")
        self.update_messages_to_remote(messages)
        with open(f'{self.log_dir}/{self.configs.project_name}_messages_log.json', 'w', encoding='utf8') as f:
            json.dump(messages, f, indent=4)

    def process_and_run_test_case(self, target_tc, target_test_case_path):
        def _extract_error_msg(log):
            error_msg = []
            stop_flag = False
            for each_line in log.split('\n'):
                if each_line.strip().startswith('[INFO]'):
                    continue
                if each_line.strip().startswith('[main]'):
                    continue
                if each_line.strip().startswith('[WARNING]'):
                    continue
                
                if each_line.strip().startswith('[ERROR] Tests run:'):
                    if stop_flag:
                        break
                    else:
                        stop_flag = True
                
                if each_line.strip().startswith('[ERROR] To see the full stack trace'):
                    break

                error_msg.append(each_line)

            error_msg = '\n'.join(error_msg)
            return error_msg

        compile_log, test_log, compile_success, execute_success = self.test_case_runner.compile_and_execute_test_case(target_tc, target_test_case_path) 

        if not compile_success:
            error_msg = _extract_error_msg(compile_log)
            fail_type = 'fail_compile'
        elif not execute_success:
            error_msg = _extract_error_msg(test_log)
            fail_type = 'fail_execute'
        else:
            error_msg = None
            fail_type = None

        return error_msg, fail_type

    def extract_target_tc(self, messages):
        target_tc = re.findall(r'```java\n(.*?)\n```', messages[-1]["content"], re.DOTALL)
        if len(target_tc) == 0:
            target_tc = re.findall(r'```(.*?)```', messages[-1]["content"], re.DOTALL)
        if len(target_tc) == 0:
            logger.error(f'[ERROR] extract target test case failed.\n{messages[-1]["content"]}')
            target_tc = messages[-1]["content"]
        else:
            target_tc = target_tc[0]

        start_idx = None
        target_tc_lines = target_tc.split('\n')
        for idx, each_line in enumerate(target_tc_lines):
            if re.findall(r'^\d+:\w', each_line):
                start_idx = idx
                break
        target_tc = '\n'.join(target_tc_lines[start_idx:])

        target_tc = self.remove_line_number_for_code(target_tc)
        return target_tc

    def remove_line_number_for_code(self, code):
        processed_lines = []
        for each_line in code.split('\n'):
            proc_line = re.sub(r"^\d+:", "", each_line.strip())
            processed_lines.append(proc_line)
        code = '\n'.join(processed_lines)
        return code

    def add_line_number_for_code(self, code):
        code_lines = code.strip().split('\n')
        code_with_line_number = []
        for idx, each_line in enumerate(code_lines):
            code_with_line_number.append(f"{idx + 1}:{each_line}")
        return '\n'.join(code_with_line_number)
    
    def get_invocation_in_a_test_case(self, test_case_path, test_case):
        os.makedirs(os.path.dirname(test_case_path), exist_ok=True)
        with open(test_case_path, 'w', encoding='utf8') as f:
            f.write(test_case)

        # codeql create database
        codeql_create_database_cmd = [CODEQL_PATH, 'database', 'create', self.configs.codeql_database_for_target_tc_path, f'--language=java', f'--source-root={self.configs.project_without_test_file_path}', f'--overwrite', '--command=mvn test-compile']
        codeql_log = subprocess.run(codeql_create_database_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if '[ERROR]' in f'{codeql_log.stdout}\n{codeql_log.stderr}':
            logger.error(f'Create database failed after adding generated test case:\n{codeql_log.stdout}\n{codeql_log.stderr}')
            # TODO use javalang to extract method invocations
            return None, None, None, None
        
        # method invocation codeql query
        with open(self.query_method_invocation_in_a_file_template_path, 'r', encoding='utf8') as f:
            query_method_invocation_template = f.read()
        
        query_method_invocation_impl = query_method_invocation_template.replace('TEST_CASE_ABSOLUTE_PATH', test_case_path)
        with open(self.query_method_invocation_in_a_file_impl_path, 'w', encoding='utf8') as f:
            f.write(query_method_invocation_impl)

        method_invocation = self.query_method_invocation_in_a_file(self.query_method_invocation_in_a_file_impl_path)

        # constructor invocation codeql query
        with open(self.query_constructor_invocation_in_a_file_template_path, 'r', encoding='utf8') as f:
            query_constructor_invocation_template = f.read()
        
        query_constructor_invocation_impl = query_constructor_invocation_template.replace('TEST_CASE_ABSOLUTE_PATH', test_case_path)
        with open(self.query_constructor_invocation_in_a_file_impl_path, 'w', encoding='utf8') as f:
            f.write(query_constructor_invocation_impl)
        
        constructor_invocation = self.query_method_invocation_in_a_file(self.query_constructor_invocation_in_a_file_impl_path)
        
        # variable declaration codeql query
        with open(self.query_variable_declaration_in_a_file_template_path, 'r', encoding='utf8') as f:
            query_variable_declaration_template = f.read()
        
        query_variable_declaration_impl = query_variable_declaration_template.replace('TEST_CASE_ABSOLUTE_PATH', test_case_path)
        with open(self.query_variable_declaration_in_a_file_impl_path, 'w', encoding='utf8') as f:
            f.write(query_variable_declaration_impl)

        variable_declaration = self.query_variable_declaration_in_a_file(self.query_variable_declaration_in_a_file_impl_path)

        all_init_invocation_nodes = []
        for init_invocation in [method_invocation, constructor_invocation]:
            for each_method, class_invoc in init_invocation.items():
                for each_class, method_signatures in class_invoc.items():
                    for each_signature in method_signatures:
                        full_signature = f"{each_class}::::{each_signature}"
                        all_init_invocation_nodes.append(full_signature)
        all_init_invocation_nodes = list(set(all_init_invocation_nodes))

        return all_init_invocation_nodes, method_invocation, constructor_invocation, variable_declaration

    def query_variable_declaration_in_a_file(self, query_path):
        query_result = self.run_query(query_path, self.configs.codeql_database_for_target_tc_path)

        variable_declaration = []
        for each_line in query_result.strip().split('\n')[2:]:
            infos = each_line.split('|')
            if len(infos) < 4:
                continue
            class_name, var_name, initializer = infos[1].strip(), infos[2].strip(), infos[3].strip()
            variable_declaration.append(f'{class_name}::::{var_name}')
        variable_declaration = list(set(variable_declaration))
        return variable_declaration
    
    def query_method_invocation_in_a_file(self, query_path):
        query_result = self.run_query(query_path, self.configs.codeql_database_for_target_tc_path)

        method_invocation = {}
        for each_line in query_result.strip().split('\n')[2:]:
            infos = each_line.split('|')
            if len(infos) < 3:
                continue
            class_name, method_signature = infos[1].strip(), infos[2].strip()
            method_name = method_signature.split('(')[0]
            m_invoc = method_invocation.get(method_name, {})
            m_c_invoc = m_invoc.get(class_name, [])
            if method_signature not in m_c_invoc:
                m_c_invoc.append(method_signature)
            m_invoc[class_name] = m_c_invoc
            method_invocation[method_name] = m_invoc
        
        return method_invocation

    def run_query(self, query_path, database_path):
        query_run_cmd = [CODEQL_PATH, 'query', 'run', f'--database={database_path}', query_path]
        query_result = subprocess.run(query_run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if 'ERROR' in f'{query_result.stdout}\n{query_result.stderr}':
            logger.error(f'Query failed:\n{query_result.stdout}\n{query_result.stderr}')
            raise ValueError('Query failed.')
        query_result = query_result.stdout
        return query_result

    def explore_knowledge_graph(self, init_method_invocation, init_constructor_invocation):
        additional_method_overload, additional_constructor_overload = self.explore_overload_relation(init_method_invocation, init_constructor_invocation)
        additional_method_parameter, additional_constructor_parameter = self.explore_parameter_relation(init_method_invocation, init_constructor_invocation)
        additional_callee_methods, additional_callee_constructors = self.explore_call_relation(init_method_invocation, init_constructor_invocation)
        additional_define_methods, additional_define_constructors = self.explore_define_relation(init_method_invocation, init_constructor_invocation)
        return additional_method_overload, additional_constructor_overload, additional_method_parameter, additional_constructor_parameter, additional_callee_methods, additional_callee_constructors, additional_define_methods, additional_define_constructors

    def explore_parameter_relation(self, init_method_invocation, init_constructor_invocation):
        # search for methods
        additional_param_info_for_method = {}  # init_method_A -> [the methods that use the init_method_A as parameter]
        for each_method, class_invoc in init_method_invocation.items():
            for each_class, method_signatures in class_invoc.items():
                for each_signature in method_signatures:
                    full_signature = f"{each_class}::::{each_signature}"
                    if full_signature in self.parameter_relation_dict:
                        related_methods = self.parameter_relation_dict[full_signature]
                        relation = additional_param_info_for_method.get(full_signature, [])
                        relation += related_methods
                        additional_param_info_for_method[full_signature] = list(set(relation))

        # search for constructors
        additional_param_info_for_constructor = {}  # init_constructor_A -> [the methods that use the constructor_A as parameter]
        for each_constructor, class_invoc in init_constructor_invocation.items():
            for each_class, constructor_signatures in class_invoc.items():
                for each_signature in constructor_signatures:
                    full_signature = f"{each_class}::::{each_signature}"
                    if full_signature in self.parameter_relation_dict:
                        related_methods = self.parameter_relation_dict[full_signature]
                        relation = additional_param_info_for_constructor.get(full_signature, [])
                        relation += related_methods
                        additional_param_info_for_constructor[full_signature] = list(set(relation))

        return additional_param_info_for_method, additional_param_info_for_constructor
    
    def explore_call_relation(self, init_method_invocation, init_constructor_invocation):
        # search for methods
        additional_callee_methods = {}  # init_method_A -> [the methods called by the init_method_A]
        for each_method, class_invoc in init_method_invocation.items():
            for each_class, method_signatures in class_invoc.items():
                for each_signature in method_signatures:
                    full_signature = f"{each_class}::::{each_signature}"
                    if full_signature in self.call_relation_dict:
                        related_methods = self.call_relation_dict[full_signature]
                        relation = additional_callee_methods.get(full_signature, [])
                        relation += related_methods
                        additional_callee_methods[full_signature] = list(set(relation))

        # search for constructors
        additional_callee_constructors = {}
        for each_constructor, class_invoc in init_constructor_invocation.items():
            for each_class, constructor_signatures in class_invoc.items():
                for each_signature in constructor_signatures:
                    full_signature = f"{each_class}::::{each_signature}"
                    if full_signature in self.call_relation_dict:
                        related_methods = self.call_relation_dict[full_signature]
                        relation = additional_callee_constructors.get(full_signature, [])
                        relation += related_methods
                        additional_callee_constructors[full_signature] = list(set(relation))
        return additional_callee_methods, additional_callee_constructors

    def explore_define_relation(self, init_method_invocation, init_constructor_invocation):
        # search for methods
        additional_define_methods = {}
        for each_method, class_invoc in init_method_invocation.items():
            for each_class, method_signatures in class_invoc.items():
                for each_signature in method_signatures:
                    full_signature = f"{each_class}::::{each_signature}"
                    if each_class in self.define_relation_dict:
                        related_methods = self.define_relation_dict[each_class]
                        relation = additional_define_methods.get(each_class, [])
                        relation += related_methods
                        additional_define_methods[full_signature] = list(set(relation))
        
        # search for constructors
        additional_define_constructors = {}
        for each_constructor, class_invoc in init_constructor_invocation.items():
            for each_class, constructor_signatures in class_invoc.items():
                for each_signature in constructor_signatures:
                    full_signature = f"{each_class}::::{each_signature}"
                    if each_class in self.define_relation_dict:
                        related_methods = self.define_relation_dict[each_class]
                        relation = additional_define_constructors.get(each_class, [])
                        relation += related_methods
                        additional_define_constructors[each_class] = list(set(relation))
        return additional_define_methods, additional_define_constructors

    def explore_overload_relation(self, init_method_invocation, init_constructor_invocation):
        additional_method_invocation = {}

        # search for overloaded methods
        for method_name, class_invoc in init_method_invocation.items():
            for class_name, method_signatures in class_invoc.items():
                for each_signature in method_signatures:
                    overload_method_signatures = self.search_overload(each_signature, class_name)
                    if len(overload_method_signatures) > 0:
                        m_invoc = additional_method_invocation.get(method_name, {})
                        m_c_invoc = m_invoc.get(class_name, [])
                        m_c_invoc += overload_method_signatures
                        m_invoc[class_name] = list(set(m_c_invoc))
                        additional_method_invocation[method_name] = m_invoc

        additional_constructor_invocation = {}
        # search for overloaded constructors
        for constructor_name, class_invoc in init_constructor_invocation.items():
            for class_name, method_signatures in class_invoc.items():
                for each_signature in method_signatures:
                    overload_constructor_signatures = self.search_overload(each_signature, class_name)
                    if len(overload_constructor_signatures) > 0:
                        c_invoc = additional_constructor_invocation.get(constructor_name, {})
                        c_c_invoc = c_invoc.get(class_name, [])
                        c_c_invoc += overload_constructor_signatures
                        c_invoc[class_name] = list(set(c_c_invoc))
                        additional_constructor_invocation[constructor_name] = c_invoc

        return additional_method_invocation, additional_constructor_invocation
        
    def search_overload(self, method_signature, class_name):
        overload_method_signatures = []
        method_name = method_signature.split('(')[0]
        if method_name in self.overload_relation_dict:
            if class_name in self.overload_relation_dict[method_name]:
                method_signature_list = self.overload_relation_dict[method_name][class_name]
                if method_signature in method_signature_list:
                    # assert method_signature in method_signature_list
                    method_signature_list.remove(method_signature)  # for spark, generate `new QueeuedThreadPool()` (maybe the generated is error), but the method signature is `QueuedThreadPool(int)` and `QueuedThreadPool(int, int, int)`
                overload_method_signatures = method_signature_list
        return overload_method_signatures

    def rank_additional_invocation(self, all_init_invocation_nodes, 
                                   init_variable_node, 
                                   invocation_node_added_by_gen,
                                   variable_node_added_by_gen,
                                   additional_method_overload, additional_constructor_overload, 
                                   additional_method_parameter, additional_constructor_parameter, 
                                   additional_callee_methods, additional_callee_constructors, 
                                   additional_define_methods, additional_define_constructors,
                                   top_k=3, score_threshold=1):
        # gather all additional_node
        all_additional_node = []

        for additional_overload in [additional_method_overload, additional_constructor_overload]:
            for each_init_method, each_init_class2additional in additional_overload.items():
                for each_init_class, explored_method_signatures in each_init_class2additional.items():
                    # add full signature
                    for each_signature in explored_method_signatures:
                        all_additional_node.append(f"{each_init_class}::::{each_signature}")

        for additional_parameter in [additional_method_parameter, additional_constructor_parameter]:
            for each_init_method, explored_method_full_signatures in additional_parameter.items():
                all_additional_node += explored_method_full_signatures

        for additional_callee in [additional_callee_methods, additional_callee_constructors]:
            for each_init_method, explored_method_full_signatures in additional_callee.items():
                all_additional_node += explored_method_full_signatures

        for additional_define in [additional_define_methods, additional_define_constructors]:
            for each_init_method_full_signature, explored_method_signatures in additional_define.items():
                each_init_class = each_init_method_full_signature.split('::::')[0]
                # add full signature
                for each_signature in explored_method_signatures:
                    all_additional_node.append(f"{each_init_class}::::{each_signature}")
        
        all_additional_node = list(set(all_additional_node))
        all_additional_node_score = {}  # full_signature -> [overload_score, parameter_score, callee_score, define_score]
        
        # calculate score
        for each_additional_node_full_signature in all_additional_node:
            score_overloead, score_parameter, score_call, score_define = self.calculate_score(each_additional_node_full_signature, all_init_invocation_nodes, init_variable_node, invocation_node_added_by_gen, variable_node_added_by_gen)

            full_score = all_additional_node_score.get(each_additional_node_full_signature, [0, 0, 0, 0])
            full_score[0] += score_overloead
            full_score[1] += score_parameter
            full_score[2] += score_call
            full_score[3] += score_define
            all_additional_node_score[each_additional_node_full_signature] = full_score

        # sort by score
        all_additional_node_sum_score = {each: sum(score) for each, score in all_additional_node_score.items()}
        all_additional_node_sum_score = sorted(all_additional_node_sum_score.items(), key=lambda x: x[1], reverse=True)
        top_additional_node_sum_score = all_additional_node_sum_score[:top_k]
        top_additional_nodes = [each[0] for each in top_additional_node_sum_score]
        top_additional_node_scores = [each[1] for each in top_additional_node_sum_score]

        return top_additional_nodes, top_additional_node_scores

    def calculate_score(self, additional_node_full_signature, all_init_invocation_nodes, init_variable_node, invocation_node_added_by_gen, variable_node_added_by_gen, weight_added_invocation_node=10, weight_added_variable_node=10):
        score_overloead = 0
        score_parameter = 0
        score_call = 0
        score_define = 0

        # the score between additional node and init invocation nodes
        for each_init_node_full_signature in all_init_invocation_nodes:
            additional_class_name, additional_signature = additional_node_full_signature.split('::::')
            init_class_name, init_signature = each_init_node_full_signature.split('::::')

            # score for overloaded relation
            if additional_class_name == init_class_name and additional_signature.split('(')[0] == init_signature.split('(')[0]:
                if init_signature in invocation_node_added_by_gen:
                    score_overloead += 1 * weight_added_invocation_node
                else:
                    score_overloead += 1
            
            # score for parameter relation
            additional_params = additional_signature.split('(')[1][:-1].split(',')
            additional_params = [each.split('.')[-1] if '.' in each else each for each in additional_params]

            init_params = init_signature.split('(')[1][:-1].split(',')
            init_params = [each.split('.')[-1] if '.' in each else each for each in init_params]
            if additional_class_name in init_params:
                if init_signature in invocation_node_added_by_gen:
                    score_parameter += 1 * weight_added_invocation_node
                else:
                    score_parameter += 1
            if init_class_name in additional_params:
                if init_signature in invocation_node_added_by_gen:
                    score_parameter += 1 * weight_added_invocation_node
                else:
                    score_parameter += 1
            
            # score for call relation
            callee_of_additional = self.call_relation_dict.get(additional_node_full_signature, [])
            callee_of_init = self.call_relation_dict.get(each_init_node_full_signature, [])
            if additional_node_full_signature in callee_of_init:
                if each_init_node_full_signature in invocation_node_added_by_gen:
                    score_call += 1 * weight_added_invocation_node
                else:
                    score_call += 1
            if each_init_node_full_signature in callee_of_additional:
                if each_init_node_full_signature in invocation_node_added_by_gen:
                    score_call += 1 * weight_added_invocation_node
                else:
                    score_call += 1

            # score for define relation
            if additional_class_name == init_class_name:
                if init_signature in invocation_node_added_by_gen:
                    score_define += 1 * weight_added_invocation_node
                else:
                    score_define += 1

        # the score between additional node and init variable node (just parameter relation)
        for each_init_variable_node in init_variable_node:
            class_name, variable_name = each_init_variable_node.split('::::')
            if class_name in additional_params:
                if each_init_variable_node in variable_node_added_by_gen:
                    score_parameter += 1 * weight_added_variable_node
                else:
                    score_parameter += 1

        return score_overloead, score_parameter, score_call, score_define

    def find_method_have_common_parameter(self, one_additional_invocation_signature, init_invocation, is_exact_match=True):
        matched_method = []
        assert is_exact_match, 'only support exact match now.'
        add_sign_params = one_additional_invocation_signature.split('(')[1]
        for each_method, class_invoc in init_invocation.items():
            for each_class, method_signatures in class_invoc.items():
                for each_signature in method_signatures:
                    if each_signature.split('(')[1] == add_sign_params:
                        matched_method.append((each_class, each_signature))
        return matched_method

    def get_parameter_relation_dict(self, method_invocation_dict):
        all_method_full_signatures = []
        for each_method_name, class_invoc in method_invocation_dict.items():
            for each_class_name, method_signatures in class_invoc.items():
                for each_signature in method_signatures:
                    all_method_full_signatures.append(f"{each_class_name}::::{each_signature}")
        
        parameter_relation_dict = {}  # method_A -> [the methods that use the method_A as parameter]
        for i in tqdm(list(range(len(all_method_full_signatures) - 1)), desc='Building parameter relation dict', ncols=100):
            for j in range(i + 1, len(all_method_full_signatures)):
                method_1 = all_method_full_signatures[i]
                class_1, signature_1 = method_1.split('::::')
                parameters_1 = signature_1.split('(')[1][:-1].split(',')
                parameters_1 = [each.split('.')[-1] if '.' in each else each for each in parameters_1]

                method_2 = all_method_full_signatures[j]
                class_2, signature_2 = method_2.split('::::')
                parameters_2 = signature_2.split('(')[1][:-1].split(',')
                parameters_2 = [each.split('.')[-1] if '.' in each else each for each in parameters_2]

                if class_1 in parameters_2:
                    relation = parameter_relation_dict.get(method_1, [])
                    relation.append(method_2)
                    parameter_relation_dict[method_1] = list(set(relation))
                if class_2 in parameters_1:
                    relation = parameter_relation_dict.get(method_2, [])
                    relation.append(method_1)
                    parameter_relation_dict[method_2] = list(set(relation))
        return parameter_relation_dict

    def get_call_relation_dict(self, method_invocation_in_a_method_table):
        call_relation_dict = {}
        for each_class, method_invoc in method_invocation_in_a_method_table.items():
            for each_signature, callee_methods in method_invoc.items():
                caller_method_full_signature = f"{each_class}::::{each_signature}"

                for each_callee_method in callee_methods:
                    callee_method_full_signature = f"{each_callee_method[0]}::::{each_callee_method[1]}"
                    relation = call_relation_dict.get(caller_method_full_signature, [])
                    relation.append(callee_method_full_signature)
                    call_relation_dict[caller_method_full_signature] = list(set(relation))

        return call_relation_dict

    def get_define_relation_dict(self, method_declaration):
        define_relation_dict = {}
        for each_info in method_declaration:
            each_class = each_info['class_name']
            method_signature = each_info['method_signature']
            signature_list = define_relation_dict.get(each_class, [])
            signature_list.append(method_signature)
            define_relation_dict[each_class] = signature_list
        return define_relation_dict


class Client:
    def __init__(self, api_key, max_query_round, knowledge_graph_path, method_invocation_in_a_method_table_path, method_invocation_in_a_file_table_path, codeql_database_for_project_path, codeql_database_for_target_tc_path, query_method_invocation_in_a_file_template_path, query_method_invocation_in_a_file_impl_path, project_without_test_file_path, prompt_message_callback=None):
        super().__init__()
        # self.client = OpenAI(api_key=api_key, base_url='https://api.key77qiqi.cn/v1')
        self.client = OpenAI(api_key=api_key, base_url='https://api.openai.com/v1')
        self.query = Query(knowledge_graph_path, method_invocation_in_a_method_table_path, method_invocation_in_a_file_table_path, codeql_database_for_project_path, codeql_database_for_target_tc_path, query_method_invocation_in_a_file_template_path, query_method_invocation_in_a_file_impl_path, project_without_test_file_path)
        self.temp = 0.0
        self.top_p = 0.1
        self.seed = 1203
        self.max_query_round = max_query_round
        # all `save_messages` operations are moved here
        self.prompt_message_callback = prompt_message_callback

    def generate_with_query(self, prompt, messages_history, fail_type=None, target_test_case_path=None, target_focal_file_abs_path=None, referable_tc_class_name=None, referable_tc_method_name=None, give_query_example=False, additional_node_knowledge=None):
        prompt_with_query = self.query.construct_prompt(
            task_desc=prompt, fail_type=fail_type, give_query_example=give_query_example,
            additional_node_knowledge=additional_node_knowledge
            )

        messages = self.generate(prompt_with_query, messages_history)

        if self.query.kg is None:
            self.query.get_knowledge_graph()

        if self.query.method_invocation_in_a_method_table is None:
            self.query.get_method_invocation_in_a_method_table()

        if self.query.method_invocation_in_a_file_table is None:
            self.query.get_method_invocation_in_a_file_table()

        if target_focal_file_abs_path is not None and self.query.method_invocation_in_focal_file is None:
            self.query.get_method_invocation_in_focal_file(target_focal_file_abs_path)
        
        if referable_tc_class_name is not None and self.query.method_invocation_in_referable_tc is None:
            self.query.get_method_invocation_in_referable_tc(referable_tc_class_name, referable_tc_method_name)

        for i in range(self.max_query_round):
            response = messages[-1]["content"]
            query_result = self.query.extract_query_result(response, fail_type=fail_type, target_test_case_path=target_test_case_path)

            if query_result is None:
                break
            else:
                messages = self.generate(query_result, messages)
        return messages
    
    def generate(self, prompt, messages_history):
        messages = messages_history + [{"role": "user", "content": prompt}]
        if self.prompt_message_callback:
            self.prompt_message_callback(messages)
        messages = self._generate(messages)
        return messages

    def _generate(self, messages):
        response = self.client.chat.completions.create(
            model="gpt-4o", messages=messages, temperature=self.temp, stream=False, top_p=self.top_p, seed=self.seed, max_tokens=3072
            ).choices[0].message.content
        messages.append({"role": "assistant", "content": response})
        if self.prompt_message_callback:
            self.prompt_message_callback(messages)
        return messages
        

class Analyzer:
    def __init__(self, client):
        super().__init__()
        self.client = client

    # TODO This is the same as Query.extract_prompt. Extract it to a general method.
    def construct_prompt(self, task_desc, fail_type=None, give_query_example=False, additional_node_knowledge=None):

        prompt = f"""Instruction for this step: Your task is:\n======\n{task_desc}\n======\n\n"""
        if additional_node_knowledge is not None and len(additional_node_knowledge) > 0:
            prompt += f"""Here are additional information that could be helpful for you:\n"""

            line_num = 1
            prompt += f"""# Method Signature or Constructor Signature\n"""
            for each in additional_node_knowledge:
                class_name, method_signature = each.split('::::')
                prompt += f"""{line_num}: {class_name} {method_signature}\n"""
                line_num += 1
            
            prompt += f"""\n"""

        if fail_type is not None:
            prompt += f"""Before performing the above task, you must actively query the method bodies of any method invocations (instead of declarations and import) about which you are confused, especially the method invocation that throws the error."""
            prompt += f"""\n- If the method that throws the error has been queried and you do not need to query any other methods, just perform the above task to output the target test case."""
            prompt += f"""\n- Otherwise, please just output only the query (instead of the target test case) consisting of the required methods' positions and names."""
            if give_query_example:
                prompt += f"""\nHere is an Example Query for illustrating the format, which requires the method bodies of the method named METHOD_NAME_1 invoked in Referable Test Case at line 6 and the method named METHOD_NAME_2 invoked in Target Focal Method at line 8:\n```\n# QUERY:\nReferable Test Case:6:METHOD_NAME_1\nTarget Focal Method:8:METHOD_NAME_2\n```\n\n"""
        else:
            prompt += f"""Before performing the above task, you must actively query the method bodies of any method invocations (instead of declarations and import) about which you are confused.\n\n"""  
            prompt += f"""- If you need to query, please just output only the query (instead of the target test case) consisting of the required methods' positions and names."""
            if give_query_example:
                prompt += f"""\nHere is an Example Query for illustrating the format, which requires the method bodies of the method named METHOD_NAME_1 invoked in Referable Test Case at line 6 and the method named METHOD_NAME_2 invoked in Target Focal Method at line 8:\n```\n# QUERY:\nReferable Test Case:6:METHOD_NAME_1\nTarget Focal Method:8:METHOD_NAME_2\n```\n\n"""
            prompt += f"""- If do not need to query, just perform the above task to output the target test case."""
        
        return prompt

    def determine_reference(self, target_focal_method, target_test_description, referable_test_case, referable_focal_method, messages_history):
        prompt = f"""# Target Focal Method\n```\n{target_focal_method}\n```\n\n"""
        prompt += f'# Target Test Case Description\n```\n{target_test_description}\n```\n\n'
        if referable_focal_method is not None:
            prompt += f"""# Referable Focal Method\n```\n{referable_focal_method}\n```\n\n"""
        else:
            prompt += f"""# Referable Focal Method\nSame as the Target Focal Method\n\n"""       
        prompt += f"""# Referable Test Case\n```\n{referable_test_case}\n```\n\n"""

        prompt += f"""Your task is to analyze the relation between Target Focal Method, Target Test Case Name, Referable Focal Method, and Referable Test Case, then to determine if the Referable Test Case is actually referable for generating the target test case. If so, please output 'YES, REFERABLE', otherwise, output 'NO, NOT REFERABLE'."""

        messages = self.client.generate(prompt, messages_history)
        return messages

    def analyze_intention(self, target_focal_method, target_focal_file, target_test_case_name, referable_test_case, referable_focal_method, messages_history):
        prompt = f"""# Target Focal Method\n```\n{target_focal_method}\n```\n\n"""
        prompt += f"""# Target Focal File\nTarget Focal Method comes from the following java file:\n```\n{target_focal_file}\n```\n\n"""
        prompt += f"""# Target Test Case Name\n```\n{target_test_case_name}\n```\n\n"""
        if referable_focal_method is not None:
            prompt += f"""# Referable Focal Method\n```\n{referable_focal_method}\n```\n\n"""
        else:
            prompt += f"""# Referable Focal Method\nSame as the Target Focal Method\n\n"""            
        prompt += f"""# Referable Test Case\n```\n{referable_test_case}\n```\n\n"""
        prompt += f"""Please infer the intention of the target test case based on Target Focal Method, Target Focal File, Target Test Case Name, Referable Focal Method, and Referable Test Case.\nYour output should describe the complete intention as much detail as possible in one sentence."""

        messages = self.client.generate(prompt, messages_history)
        return messages
    
    def do_not_analyze_skip_to_modification(self, target_focal_method, target_focal_file, target_test_description, referable_test_case, referable_focal_method, messages_history):
        prompt = f"""# Target Focal Method\n```\n{target_focal_method}\n```\n\n"""
        prompt += f"""# Target Focal File\nTarget Focal Method comes from the following java file:\n```\n{target_focal_file}\n```\n\n"""
        prompt += f'# Target Test Case Description\n```\n{target_test_description}\n```\n\n'
        if referable_focal_method is not None:
            prompt += f"""# Referable Focal Method\n```\n{referable_focal_method}\n```\n\n"""
        else:
            prompt += f"""# Referable Focal Method\nSame as the Target Focal Method\n\n"""            
        prompt += f"""# Referable Test Case\n```\n{referable_test_case}\n```\n\n"""
        
        # prompt += f"""Please infer the intention of the target test case based on Target Focal Method, Target Focal File, Target Test Case Name, Referable Focal Method, and Referable Test Case.\nYour output should describe the complete intention as much detail as possible in one sentence."""
        
        # ↓ this is the same as Generator.make_first_modification
        general_description = """According to Target Test case Description, please think about which code lines of Referable Test Case should be modified, thus generating the Target Test Case.\nREQUIREMENTS:\n1. Your output should be only the target test case.\n2. the target test case has line numbers (e.g., `1:package ...`) and is encapsulated by triple backticks (i.e., ```);\n3. does not contain assertion statements.\n4. must double check the import statements to ensure all necessary dependencies are imported.\n4. Actively use the QUERY to understand method invocations."""
        prompt += self.construct_prompt(general_description, give_query_example=True)

        messages = self.client.generate(prompt, messages_history)
        return messages

    def analyze_error_msg(self, error_msg, messages_history):
        prompt = f"""When executing the target test case, I encounter the following errors:\n```\n{error_msg}\n```\nPlease analyze the errors and locate which lines in the target test case throw the errors. Your output should only describe the analysis results."""
        messages = self.client.generate(prompt, messages_history)
        return messages

    def final_check(self, messages_history):
        prompt = f"""The Target Test Case has been successfully compiled and executed.\nPlease check whether its test method executes the Target Focal Method and aligns with the intention.\n- If so, output only "FINISH GENERATION",\n- Otherwise, please output only the analysis."""
        messages = self.client.generate(prompt, messages_history)
        return messages


class Query:
    def __init__(self, knowledge_graph_path, method_invocation_in_a_method_table_path, method_invocation_in_a_file_table_path, codeql_database_for_project_path, codeql_database_for_target_tc_path, query_method_invocation_in_a_file_template_path, query_method_invocation_in_a_file_impl_path, project_without_test_file_path):
        super().__init__()
        self.kg = None
        self.method_invocation_in_a_method_table = None
        self.method_invocation_in_a_file_table = None

        self.knowledge_graph_path = knowledge_graph_path
        self.method_invocation_in_a_method_table_path = method_invocation_in_a_method_table_path
        self.method_invocation_in_a_file_table_path = method_invocation_in_a_file_table_path

        self.method_invocation_in_focal_file = None
        self.method_invocation_in_referable_tc = None

        self.project_without_test_file_path = project_without_test_file_path
        self.codeql_database_for_project_path = codeql_database_for_project_path
        self.codeql_database_for_target_tc_path = codeql_database_for_target_tc_path
        self.query_method_invocation_in_a_file_template_path = query_method_invocation_in_a_file_template_path
        self.query_method_invocation_in_a_file_impl_path = query_method_invocation_in_a_file_impl_path
        self.max_invoc_example = 2
        self.max_num_query_mehtod = 5
        self.max_body_lines = 100
        self.max_info_for_each_method = 3
        self.max_lines_of_query = 800

    def construct_prompt(self, task_desc, fail_type=None, give_query_example=False, additional_node_knowledge=None):

        prompt = f"""Instruction for this step: Your task is:\n======\n{task_desc}\n======\n\n"""
        if additional_node_knowledge is not None and len(additional_node_knowledge) > 0:
            prompt += f"""Here are additional information that could be helpful for you:\n"""

            line_num = 1
            prompt += f"""# Method Signature or Constructor Signature\n"""
            for each in additional_node_knowledge:
                class_name, method_signature = each.split('::::')
                prompt += f"""{line_num}: {class_name} {method_signature}\n"""
                line_num += 1
            
            prompt += f"""\n"""

        if fail_type is not None:
            prompt += f"""Before performing the above task, you must actively query the method bodies of any method invocations (instead of declarations and import) about which you are confused, especially the method invocation that throws the error."""
            prompt += f"""\n- If the method that throws the error has been queried and you do not need to query any other methods, just perform the above task to output the target test case."""
            prompt += f"""\n- Otherwise, please just output only the query (instead of the target test case) consisting of the required methods' positions and names."""
            if give_query_example:
                prompt += f"""\nHere is an Example Query for illustrating the format, which requires the method bodies of the method named METHOD_NAME_1 invoked in Referable Test Case at line 6 and the method named METHOD_NAME_2 invoked in Target Focal Method at line 8:\n```\n# QUERY:\nReferable Test Case:6:METHOD_NAME_1\nTarget Focal Method:8:METHOD_NAME_2\n```\n\n"""
        else:
            prompt += f"""Before performing the above task, you must actively query the method bodies of any method invocations (instead of declarations and import) about which you are confused.\n\n"""  
            prompt += f"""- If you need to query, please just output only the query (instead of the target test case) consisting of the required methods' positions and names."""
            if give_query_example:
                prompt += f"""\nHere is an Example Query for illustrating the format, which requires the method bodies of the method named METHOD_NAME_1 invoked in Referable Test Case at line 6 and the method named METHOD_NAME_2 invoked in Target Focal Method at line 8:\n```\n# QUERY:\nReferable Test Case:6:METHOD_NAME_1\nTarget Focal Method:8:METHOD_NAME_2\n```\n\n"""
            prompt += f"""- If do not need to query, just perform the above task to output the target test case."""
        
        return prompt
    
    def extract_query_result(self, response, fail_type, target_test_case_path):
        if '# QUERY:' in response:
            query = re.findall(r'```\n# QUERY:\n(.*?)\n```', response, re.DOTALL)
            if len(query) == 0:
                query = response.split('# QUERY:')[1].strip()
            else:
                query = query[0].strip()
            method_to_query = []
            for each_line in query.split('\n'):
                split_line = each_line.split(':')
                if len(split_line) != 3 or not split_line[1].strip().isdigit():
                    continue
                method_name = split_line[2].strip()
                method_name = method_name.split('.')[1].strip() if '.' in method_name else method_name
                method_name = method_name[1:-1].strip() if method_name.startswith('<') and method_name.endswith('>') else method_name
                method_name = method_name.split('(')[0].strip() if '(' in method_name else method_name
                method_to_query.append((split_line[0].strip(), int(split_line[1].strip()), method_name))
            
            if len(method_to_query) > self.max_num_query_mehtod:
                logger.warning(f'[Warning] The number of methods to query is reduced to the maximum ({len(method_to_query)} -> {self.max_num_query_mehtod}).')
                method_to_query = method_to_query[:self.max_num_query_mehtod]
            method_knowledge = self.query_method_body_and_invocation(method_to_query, fail_type, target_test_case_path)

            if len(method_knowledge) == 0:
                query_result = f"""The required method body is not available. Do not query this method again."""
            else:
                query_result = f"""The required method body and usage example are as follows:\n"""
                for each in method_knowledge:
                    method_body_lines = each[1].strip().split('\n')
                    if len(method_body_lines) > self.max_body_lines:
                        logger.warning(f'[Warning] The number of method body lines is reduced to the maximum ({len(method_body_lines)} -> {self.max_body_lines}).')
                        method_body_lines = method_body_lines[:self.max_body_lines]
                    method_body = '\n'.join(method_body_lines)
                    query_result += f"""Method Name: {each[0]}\nMethod Body:\n```\n\n{method_body}\n```\n"""

                    for invoc_i, each_invoc in enumerate(each[2][:self.max_invoc_example]):
                        invoc_body_lines = each_invoc.strip().split('\n')
                        if len(invoc_body_lines) > self.max_body_lines:
                            logger.warning(f'[Warning] The number of invocation body lines is reduced to the maximum ({len(invoc_body_lines)} -> {self.max_body_lines}).')
                            invoc_body_lines = invoc_body_lines[:self.max_body_lines]
                        invoc_body = '\n'.join(invoc_body_lines)

                        query_result += f"""Method Invocation Examples {invoc_i + 1}:\n```\n{invoc_body}\n```\n\n"""
            
            query_result_lines = query_result.split('\n')
            if len(query_result_lines) > self.max_lines_of_query:
                logger.warning(f'[Warning] The number of query result lines is reduced to the maximum ({len(query_result_lines)} -> {self.max_lines_of_query}).')
                query_result_lines = query_result_lines[:self.max_lines_of_query]
                query_result = '\n'.join(query_result_lines)

            return query_result
        else:
            return None
        
    def get_method_body(self, method_name):
        return self.kg.get_method_body(method_name)
    
    def query_method_body_and_invocation(self, method_infos, fail_type, target_test_case_path):
        method_invocation_in_generated_test_case = None
        method_detail_infos = []
        method_name_record = []
        position_list = ['Target Test Case', 'Target Focal Method', 'Target Focal File', 'Referable Test Case']

        for each_info in method_infos:
            loc_file, loc_line, method_name = each_info
            if method_name in method_name_record:
                continue
            method_name_record.append(method_name)

            if loc_file in position_list:
                start_pos = position_list.index(loc_file)
                try_loc_file_list = position_list[start_pos:] + position_list[:start_pos]
            else:
                try_loc_file_list = position_list

            for possible_loc_file in try_loc_file_list:
                if possible_loc_file == 'Target Test Case':
                    if method_invocation_in_generated_test_case is None:
                        method_invocation_in_generated_test_case = self.get_method_invocation_in_generated_test_case(test_case_abs_path=target_test_case_path, fail_type=fail_type)
                        if method_invocation_in_generated_test_case is None:
                            continue
                    
                    m_info = self.get_invocated_method_info(
                        method_name=method_name, 
                        info_collection=method_invocation_in_generated_test_case
                        )
                elif possible_loc_file == 'Target Focal Method' or loc_file == 'Target Focal File':
                    m_info = self.get_invocated_method_info(
                        method_name=method_name, 
                        info_collection=self.method_invocation_in_focal_file
                        )
                elif possible_loc_file == 'Referable Test Case':
                    m_info = self.get_invocated_method_info(
                        method_name=method_name, 
                        info_collection=self.method_invocation_in_referable_tc
                        )
                # TODO consider Referable Focal Method

                if len(m_info) > 0:
                    method_detail_infos += m_info
                    break
            
            # consider the full project knowledge graph
            if len(m_info) == 0:
                if method_name in self.kg:
                    for class_name, method_signature_dict in self.kg[method_name].items():
                        for method_signature, _ in method_signature_dict.items():
                            m_info.append((method_name, class_name, method_signature))
                    method_detail_infos += m_info
        
        method_knowledge = []
        for m_detail in method_detail_infos:
            each_method_knowledge = []
            method_name, method_class, method_signature = m_detail
            if method_name in self.kg:
                if method_class is None or method_signature is None:
                    for class_name, method_signature_dict in self.kg[method_name].items():
                        for method_signature, method_body_invoc in method_signature_dict.items():
                            # filter out the info from target test case
                            method_invoc_filtered = []
                            for path_and_invoc in method_body_invoc['invocation_info']:
                                invoc_path = path_and_invoc[0].replace('/repos_with_test/', '/repos_removing_test/')
                                if invoc_path != target_test_case_path:
                                    method_invoc_filtered.append(path_and_invoc[1])
                            each_method_knowledge.append(
                                (
                                    f'{class_name}.{method_name}', 
                                    method_body_invoc['method_body'], 
                                    method_invoc_filtered
                                )
                                )

                elif method_class in self.kg[method_name]:
                    if method_signature in self.kg[method_name][method_class]:
                        method_body = self.kg[method_name][method_class][method_signature]['method_body']
                        method_invocation_info = self.kg[method_name][method_class][method_signature]['invocation_info']
                        # filter out the info from target test case
                        method_invoc_filtered = []
                        for path_and_invoc in method_invocation_info:
                            invoc_path = path_and_invoc[0].replace('/repos_with_test/', '/repos_removing_test/')
                            if invoc_path != target_test_case_path:
                                method_invoc_filtered.append(path_and_invoc[1])
                        each_method_knowledge.append(
                            (method_name, 
                             method_body, 
                             method_invoc_filtered)
                            )
                if len(each_method_knowledge) > self.max_info_for_each_method:
                    logger.warning(f'[Warning] The number of method knowledge for {method_name} is reduced to the maximum ({len(each_method_knowledge)} -> {self.max_info_for_each_method}).')
                    each_method_knowledge = each_method_knowledge[: self.max_info_for_each_method]
                method_knowledge += each_method_knowledge
        return method_knowledge

    def add_line_number_for_code(self, code):
        code_lines = code.strip().split('\n')
        code_with_line_number = []
        for idx, each_line in enumerate(code_lines):
            code_with_line_number.append(f"{idx + 1}\t{each_line}")
        return '\n'.join(code_with_line_number)

    def get_invocated_method_info(self, method_name, info_collection):
        method_detail_infos = []
        if method_name in info_collection:
            for each_method_info in info_collection[method_name]:
                method_class, method_signature = each_method_info
                method_detail_infos.append((method_name, method_class, method_signature))
        return method_detail_infos

    def get_method_invocation_in_referable_tc(self, referable_tc_class_name, referable_tc_method_name):
        # print('get_method_invocation_in_referable_tc...')
        method_invocation = {}
        referable_tc_method_signarture = f'{referable_tc_method_name}()'
        if referable_tc_class_name in self.method_invocation_in_a_method_table:
            if referable_tc_method_signarture in self.method_invocation_in_a_method_table[referable_tc_class_name]:
                invocation_infos = self.method_invocation_in_a_method_table[referable_tc_class_name][referable_tc_method_signarture]
                for each_invo in invocation_infos:
                    invocation_class_name, invocation_method_signature  = each_invo
                    invocation_method_name = invocation_method_signature.split('(')[0]
                    m_invoc = method_invocation.get(invocation_method_name, [])
                    m_invoc.append((invocation_class_name, invocation_method_signature))
                    method_invocation[invocation_method_name] = m_invoc

        self.method_invocation_in_referable_tc = method_invocation

    def get_method_invocation_in_focal_file(self, target_focal_file_abs_path):
        print('get_method_invocation_in_focal_file...')
        method_invocation = {}
        search_key = target_focal_file_abs_path.replace('/repos_removing_test/', '/repos_with_test/')
        if search_key in self.method_invocation_in_a_file_table:
            invocation_infos = self.method_invocation_in_a_file_table[search_key]
            for each_invo in invocation_infos:
                invocation_class_name, invocation_method_signature  = each_invo
                invocation_method_name = invocation_method_signature.split('(')[0]
                m_invoc = method_invocation.get(invocation_method_name, [])
                m_invoc.append((invocation_class_name, invocation_method_signature))
                method_invocation[invocation_method_name] = m_invoc
        self.method_invocation_in_focal_file = method_invocation

    def get_knowledge_graph(self):
        with open(self.knowledge_graph_path, 'r', encoding='utf8') as f:
            self.kg = json.load(f)  # for the full project. {method_name: {class_name: {method_signature: {method_body: str, invocation_info: [str]}}}
        assert len(self.kg) > 0, "Knowledge Graph is empty."

    def get_method_invocation_in_a_method_table(self):
        with open(self.method_invocation_in_a_method_table_path, 'r', encoding='utf8') as f:
            self.method_invocation_in_a_method_table = json.load(f)
        assert len(self.method_invocation_in_a_method_table) > 0, "method_invocation_in_a_method_table is empty."  

    def get_method_invocation_in_a_file_table(self):
        with open(self.method_invocation_in_a_file_table_path, 'r', encoding='utf8') as f:
            self.method_invocation_in_a_file_table = json.load(f)
        assert len(self.method_invocation_in_a_file_table) > 0, "method_invocation_in_a_file_table is empty."

    def get_method_invocation_in_generated_test_case(self, test_case_abs_path, fail_type):
        if fail_type == 'fail_compile':
            return None

        codeql_create_database_cmd = [CODEQL_PATH, 'database', 'create', self.codeql_database_for_target_tc_path, f'--language=java', f'--source-root={self.project_without_test_file_path}', f'--overwrite']
        codeql_log = subprocess.run(codeql_create_database_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if '[ERROR]' in f'{codeql_log.stdout}\n{codeql_log.stderr}':
            logger.error(f'Create database failed after adding generated test case:\n{codeql_log.stdout}\n{codeql_log.stderr}')
            return None
        
        return self.analyze_method_invocation_in_a_file(test_case_abs_path, self.codeql_database_for_target_tc_path)
    
    def analyze_method_invocation_in_a_file(self, file_abs_path, codeql_dbs_path):  
        with open(self.query_method_invocation_in_a_file_template_path, 'r', encoding='utf8') as f:
            codeql_template = f.read()
        
        codeql_impl = codeql_template.replace('TEST_CASE_ABSOLUTE_PATH', file_abs_path)
        with open(self.query_method_invocation_in_a_file_impl_path, 'w', encoding='utf8') as f:
            f.write(codeql_impl)

        query_run_cmd = [CODEQL_PATH, 'query', 'run', f'--database={codeql_dbs_path}', self.query_method_invocation_in_a_file_impl_path]
        query_result = subprocess.run(query_run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        query_result = query_result.stdout

        method_invocation = {}
        for each_line in query_result.strip().split('\n')[2:]:
            infos = each_line.split('|')
            if len(infos) < 3:
                logger.warn(f'[Warning] abnormal query result ({file_abs_path}):\n{query_result}')
                continue
            class_name, method_signature = infos[1].strip(), infos[2].strip()
            method_name = method_signature.split('(')[0]
            m_invoc = method_invocation.get(method_name, [])
            m_invoc.append((class_name, method_signature))
            method_invocation[method_name] = m_invoc
        
        return method_invocation


class Generator:
    def __init__(self, client: Client):
        super().__init__()
        self.client = client

    def make_first_modification(self, messages_history, target_test_case_path, target_focal_file_abs_path, referable_tc_class_name, referable_tc_method_name):
        prompt = """According to Target Test case Description, please think about which code lines of Referable Test Case should be modified, thus generating the Target Test Case.\nREQUIREMENTS:\n1. Your output should be only the target test case.\n2. the target test case has line numbers (e.g., `1:package ...`) and is encapsulated by triple backticks (i.e., ```);\n3. does not contain assertion statements.\n4. must double check the import statements to ensure all necessary dependencies are imported.\n4. Actively use the QUERY to understand method invocations."""
        
        messages = self.client.generate_with_query(prompt, messages_history, 
                                                   target_test_case_path=target_test_case_path, 
                                                   target_focal_file_abs_path=target_focal_file_abs_path, 
                                                   referable_tc_class_name=referable_tc_class_name, 
                                                   referable_tc_method_name=referable_tc_method_name, 
                                                   give_query_example=True)

        return messages


    def make_modification(self, messages_history, fail_type, target_test_case_path, target_focal_file_abs_path, referable_tc_class_name, referable_tc_method_name, additional_node_knowledge):
        prompt = f"""Please carefully review the target test case and revise it. When modifying, you must comply with the REQUIREMENTS. Your output should only be the revised target test case.\nREQUIREMENTS:\n1. Your output should be only the target test case.\n2. the target test case has line numbers (e.g., `1:package ...`) and is encapsulated by triple backticks (i.e., ```);\n3. does not contain assertion statements.\n4. Actively use the QUERY to understand method invocations.\n\n"""
        
        # or GPT-4o won't care about QUERY
        prompt += f"""Here is an Example Query for illustrating the format, which requires the method bodies of the method named METHOD_NAME_1 invoked in Referable Test Case at line 6 and the method named METHOD_NAME_2 invoked in Target Focal Method at line 8:\n```\n# QUERY:\nReferable Test Case:6:METHOD_NAME_1\nTarget Focal Method:8:METHOD_NAME_2\n```\n\n"""

        messages = self.client.generate_with_query(
            prompt, messages_history, 
            fail_type=fail_type, target_test_case_path=target_test_case_path, 
            target_focal_file_abs_path=target_focal_file_abs_path, 
            referable_tc_class_name=referable_tc_class_name,
            referable_tc_method_name=referable_tc_method_name,
            additional_node_knowledge=additional_node_knowledge,
            )
        return messages
