import argparse
import json
import re
import sys
import os
import subprocess
from server import ModelQuerySession
from openai import OpenAI

sys.path.append('..')
from test_case_runner import TestCaseRunner

class RAGTesterNoReference:
    def __init__(self, configs, junit_version=5, max_round=5):
        super().__init__()
        self.configs = configs
        self.test_case_runner = TestCaseRunner(configs, configs.test_case_running_log_dir)
        api_key = configs.openai_api_key
        self.junit_version = junit_version
        
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
        self.system_prompt_maker = lambda junit_version : f"""You are an expert in Junit test case generation with Junit version {junit_version}. I will give you a target focal method and relevant information. Your task is to generate a target test case with a specified name for a given target focal method. I will guide you to complete the task step by step. Please strictly follow my each instruction."""

        self.log_dir = './data/log'
        os.makedirs(self.log_dir, exist_ok=True)

    def update_messages_to_remote(self, messages):
        # TODO notify front-end for messages, maybe trasmit full (instead of transmit update only)?
        if self.query_session:
            self.query_session.update_messages(messages)

    def save_messages(self, messages):
        self.update_messages_to_remote(messages)
        with open(f'{self.log_dir}/{self.configs.project_name}_messages_log.json', 'w', encoding='utf8') as f:
            json.dump(messages, f, indent=4)
        
    def generate_test_case(self, target_focal_method, target_focal_file, target_test_case_name, referable_test_case, referable_focal_method, target_test_case_path, target_focal_file_abs_path, referable_tc_class_name, referable_tc_method_name, referable_test_case_path, query_session: ModelQuerySession | None = None):
        self.query_session = query_session

        success_gen = False
        generated_test_case = None

        self.junit_version = query_session.junit_version

        messages = [{"role": "system", "content": f"{self.system_prompt_maker(self.junit_version)}"}]

        self.save_messages(messages)

        # add line number for code
        target_focal_method = self.add_line_number_for_code(target_focal_method)
        target_focal_file = self.add_line_number_for_code(target_focal_file)
        referable_test_case = None
        referable_focal_method = None
        referable_tc_class_name = None
        referable_tc_class_name = None

        self.client.query.method_invocation_in_focal_file = None
        
        # start generation
        for round_i in range(self.max_round + 1):
            # Generate
            if round_i == 0:
                messages = self.analyzer.analyze_intention(target_focal_method, target_focal_file, target_test_case_name, messages)
                messages = self.generator.make_first_generation(messages, target_test_case_path, target_focal_file_abs_path)
            else:
                messages = self.generator.make_modification(messages, fail_type, target_test_case_path, target_focal_file_abs_path)
            
            # Run test case
            generated_test_case = self.extract_target_tc(messages)
            # TEST check
            if generated_test_case.split('\n')[0].startswith('1'):
                print()
                raise ValueError('generated test case should not contain line number')
            error_msg, fail_type = self.process_and_run_test_case(generated_test_case, target_test_case_path)

            # Analyze running result
            if error_msg is None:
                messages = self.analyzer.final_check(messages)
            else:
                messages = self.analyzer.analyze_error_msg(error_msg, messages)

            # Check if generation is successful
            if error_msg is None and "FINISH GENERATION" in messages[-1]["content"]:
                success_gen = True
                break
            elif error_msg is None and "FINISH GENERATION" not in messages[-1]["content"]:
                print('generation does not align with the intention')
        
        if os.path.exists(target_test_case_path):
            os.remove(target_test_case_path)

        # TEST
        with open(f'{self.log_dir}/{self.configs.project_name}_messages_log.txt', 'w') as f:
            for each in messages:
                f.write(f"==={each['role']}===\n{each['content']}\n\n")
        
        if success_gen:
            print("Test case generation successfully.\n")
        else:
            print("Test case generation failed.\n")
        #

        return messages, generated_test_case, 'referable', fail_type

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
            print(f'[ERROR] extract target test case failed.\n{messages[-1]["content"]}')
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
        self.prompt_message_callback = prompt_message_callback

    def generate_with_query(self, prompt, messages_history, fail_type=None, target_test_case_path=None, target_focal_file_abs_path=None, give_query_example=False):
        prompt_with_query = self.query.construct_prompt(task_desc=prompt, fail_type=fail_type, give_query_example=give_query_example)

        messages = messages_history + [{"role": "user", "content": prompt_with_query}]
        messages = self._generate(messages)

        if self.query.kg is None:
            self.query.get_knowledge_graph()

        if self.query.method_invocation_in_a_method_table is None:
            self.query.get_method_invocation_in_a_method_table()

        if self.query.method_invocation_in_a_file_table is None:
            self.query.get_method_invocation_in_a_file_table()

        if target_focal_file_abs_path is not None and self.query.method_invocation_in_focal_file is None:
            self.query.get_method_invocation_in_focal_file(target_focal_file_abs_path)

        for i in range(self.max_query_round):
            response = messages[-1]["content"]
            query_result = self.query.extract_query_result(response, fail_type=fail_type, target_test_case_path=target_test_case_path)

            if query_result is None:
                break
            else:
                messages.append({"role": "user", "content": query_result})
                if self.prompt_message_callback:
                    self.prompt_message_callback(messages)
                messages = self._generate(messages)
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

    def analyze_intention(self, target_focal_method, target_focal_file, target_test_case_name, messages_history):
        prompt = f"""# Target Focal Method\n```\n{target_focal_method}\n```\n\n"""
        prompt += f"""# Target Focal File\nTarget Focal Method comes from the following java file:\n```\n{target_focal_file}\n```\n\n"""
        prompt += f"""# Target Test Case Name\n```\n{target_test_case_name}\n```\n\n"""
        prompt += f"""Please infer the intention of the target test case based on Target Focal Method, Target Focal File, and Target Test Case Name.\nYour output should describe the complete intention as much detail as possible in one sentence."""

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

    def construct_prompt(self, task_desc, fail_type=None, give_query_example=False):

        prompt = f"""Instruction for this step: Your task is:\n======\n{task_desc}\n======\n\n"""
        if fail_type is not None:
            prompt += f"""Before performing the above task, you must actively query the method bodies of any method invocations (instead of declarations and import) about which you are confused, especially the method invocation that throws the error."""
            prompt += f"""\n- If the method that throws the error has been queried and you do not need to query any other methods, just perform the above task to output the target test case."""
            prompt += f"""\n- Otherwise, please just output only the query (instead of the target test case) consisting of the required methods' positions and names."""
            if give_query_example:
                prompt += f"""\nHere is an Example Query for illustrating the format, which requires the method bodies of the method named METHOD_NAME_1 invoked in Target Test Case at line 6 and the method named METHOD_NAME_2 invoked in Target Focal Method at line 8:\n```\n# QUERY:\nTarget Test Case:6:METHOD_NAME_1\nTarget Focal Method:8:METHOD_NAME_2\n```\n\n"""
        else:
            prompt += f"""Before performing the above task, you must actively query the method bodies of any method invocations (instead of declarations and import) about which you are confused.\n\n"""  
            prompt += f"""- If you need to query, please just output only the query (instead of the target test case) consisting of the required methods' positions and names."""
            if give_query_example:
                prompt += f"""\nHere is an Example Query for illustrating the format, which requires the method bodies of the method named METHOD_NAME_1 invoked in Target Test Case at line 6 and the method named METHOD_NAME_2 invoked in Target Focal Method at line 8:\n```\n# QUERY:\nTarget Test Case:6:METHOD_NAME_1\nTarget Focal Method:8:METHOD_NAME_2\n```\n\n"""
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
                print(f'[Warning] The number of methods to query is reduced to the maximum ({len(method_to_query)} -> {self.max_num_query_mehtod}).')
                method_to_query = method_to_query[:self.max_num_query_mehtod]
            method_knowledge = self.query_method_body_and_invocation(method_to_query, fail_type, target_test_case_path)

            if len(method_knowledge) == 0:
                query_result = f"""The required method body is not available. Do not query this method again."""
            else:
                query_result = f"""The required method body and usage example are as follows:\n"""
                for each in method_knowledge:
                    method_body_lines = each[1].strip().split('\n')
                    if len(method_body_lines) > self.max_body_lines:
                        print(f'[Warning] The number of method body lines is reduced to the maximum ({len(method_body_lines)} -> {self.max_body_lines}).')
                        method_body_lines = method_body_lines[:self.max_body_lines]
                    method_body = '\n'.join(method_body_lines)
                    query_result += f"""Method Name: {each[0]}\nMethod Body:\n```\n\n{method_body}\n```\n"""

                    for invoc_i, each_invoc in enumerate(each[2][:self.max_invoc_example]):
                        invoc_body_lines = each_invoc.strip().split('\n')
                        if len(invoc_body_lines) > self.max_body_lines:
                            print(f'[Warning] The number of invocation body lines is reduced to the maximum ({len(invoc_body_lines)} -> {self.max_body_lines}).')
                            invoc_body_lines = invoc_body_lines[:self.max_body_lines]
                        invoc_body = '\n'.join(invoc_body_lines)

                        query_result += f"""Method Invocation Examples {invoc_i + 1}:\n```\n{invoc_body}\n```\n\n"""
            
            query_result_lines = query_result.split('\n')
            if len(query_result_lines) > self.max_lines_of_query:
                print(f'[Warning] The number of query result lines is reduced to the maximum ({len(query_result_lines)} -> {self.max_lines_of_query}).')
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
        position_list = ['Target Test Case', 'Target Focal Method', 'Target Focal File']

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
                    print(f'[Warning] The number of method knowledge for {method_name} is reduced to the maximum ({len(each_method_knowledge)} -> {self.max_info_for_each_method}).')
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
        with open(self.knowledge_graph_path, 'r') as f:
            self.kg = json.load(f)  # for the full project. {method_name: {class_name: {method_signature: {method_body: str, invocation_info: [str]}}}
        assert len(self.kg) > 0, "Knowledge Graph is empty."

    def get_method_invocation_in_a_method_table(self):
        with open(self.method_invocation_in_a_method_table_path, 'r') as f:
            self.method_invocation_in_a_method_table = json.load(f)
        assert len(self.method_invocation_in_a_method_table) > 0, "method_invocation_in_a_method_table is empty."  

    def get_method_invocation_in_a_file_table(self):
        with open(self.method_invocation_in_a_file_table_path, 'r') as f:
            self.method_invocation_in_a_file_table = json.load(f)
        assert len(self.method_invocation_in_a_file_table) > 0, "method_invocation_in_a_file_table is empty."

    def get_method_invocation_in_generated_test_case(self, test_case_abs_path, fail_type):
        if fail_type == 'fail_compile':
            return None

        codeql_create_database_cmd = ['/root/codeql/codeql', 'database', 'create', self.codeql_database_for_target_tc_path, f'--language=java', f'--source-root={self.project_without_test_file_path}', f'--overwrite']
        codeql_log = subprocess.run(codeql_create_database_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if '[ERROR]' in f'{codeql_log.stdout}\n{codeql_log.stderr}':
            print(f'{codeql_log.stdout}\n{codeql_log.stderr}\nCreate database failed after adding generated test case.')
            return None
        
        return self.analyze_method_invocation_in_a_file(test_case_abs_path, self.codeql_database_for_target_tc_path)
    
    def analyze_method_invocation_in_a_file(self, file_abs_path, codeql_dbs_path):  
        with open(self.query_method_invocation_in_a_file_template_path, 'r') as f:
            codeql_template = f.read()
        
        codeql_impl = codeql_template.replace('TEST_CASE_ABSOLUTE_PATH', file_abs_path)
        with open(self.query_method_invocation_in_a_file_impl_path, 'w') as f:
            f.write(codeql_impl)

        query_run_cmd = ['/root/codeql/codeql', 'query', 'run', f'--database={codeql_dbs_path}', self.query_method_invocation_in_a_file_impl_path]
        query_result = subprocess.run(query_run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        query_result = query_result.stdout

        method_invocation = {}
        for each_line in query_result.strip().split('\n')[2:]:
            infos = each_line.split('|')
            if len(infos) < 3:
                print(f'[Warning] abnormal query result ({file_abs_path}):\n{query_result}')
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

    def make_first_generation(self, messages_history, target_test_case_path, target_focal_file_abs_path):
        prompt = """Please generate the Target Test Case.\nREQUIREMENTS:\n1. Your output should be only the target test case.\n2. the target test case has line numbers (e.g., `1:package ...`) and is encapsulated by triple backticks (i.e., ```);\n3. does not contain assertion statements.\n4. Actively use the QUERY to understand method invocations."""
        
        messages = self.client.generate_with_query(prompt, messages_history, 
                                                   target_test_case_path=target_test_case_path, 
                                                   target_focal_file_abs_path=target_focal_file_abs_path, 
                                                   give_query_example=True)

        return messages


    def make_modification(self, messages_history, fail_type, target_test_case_path, target_focal_file_abs_path):
        prompt = f"""Please carefully review the target test case and revise it. When modifying, you must comply with the REQUIREMENTS. Your output should only be the revised target test case.\nREQUIREMENTS:\n1. Your output should be only the target test case.\n2. the target test case has line numbers (e.g., `1:package ...`) and is encapsulated by triple backticks (i.e., ```);\n3. does not contain assertion statements.\n4. Actively use the QUERY to understand method invocations."""

        messages = self.client.generate_with_query(
            prompt, messages_history, 
            fail_type=fail_type, target_test_case_path=target_test_case_path, 
            target_focal_file_abs_path=target_focal_file_abs_path
            )
        return messages
