import os
import subprocess
import json

from configs import Configs
from collections import namedtuple
from tqdm import tqdm
MethodDeclaration = namedtuple('MethodDeclaration', ['class_name', 'method_signature', 'method_start_line', 'method_end_line', 'file_path'])
MethodInvocation = namedtuple('MethodInvocation', ['callee_class_name', 'callee_method_signature', 'invoker_start_line', 'invoker_end_line', 'invoker_file_path', 'invoker_class_name', 'invoker_method_signature'])

import logging
logger = logging.getLogger(__name__)

from user_config import global_config
CODEQL_PATH = global_config['tools']['codeql']

def create_database(database_path, java_project_path):
    cmd = [CODEQL_PATH, 'database', 'create', database_path, '--language=java', f'--source-root={java_project_path}', '--overwrite', "--command=mvn clean test-compile"]
    result = subprocess.run(cmd, cwd=java_project_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8')

    if '[ERROR]' in result.stdout:
        logger.error(f'Failed to create CodeQL database:\nstdout:{result.stdout}\nstderr:{result.stderr}')
        return False
    else:
        return True


def collect_method_declarations(database_path, method_decl_query_path, constructor_decl_query_path):
    assert os.path.exists(method_decl_query_path), f'Query not found: {method_decl_query_path}'
    assert os.path.exists(constructor_decl_query_path), f'Query not found: {constructor_decl_query_path}'
    method_declarations = []

    for query_path in [method_decl_query_path, constructor_decl_query_path]:
        query_run_cmd = [CODEQL_PATH, 'query', 'run', f'--database={database_path}', query_path]

        query_result = subprocess.run(query_run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8')
        query_result = query_result.stdout
        
        for each_line in query_result.strip().split('\n')[2:]:
            infos = each_line.split('|')
            class_name, method_signature, method_start_line, method_end_line, file_path = infos[1].strip(), infos[2].strip(), infos[3].strip(), infos[4].strip(), infos[5].strip()

            m_declaration = MethodDeclaration(class_name, method_signature, int(method_start_line), int(method_end_line), file_path)

            method_declarations.append(m_declaration)
    return method_declarations


def collect_method_invocations(database_path, method_invoc_query_path, constructor_invoc_query_path):  # including constructor invocations
    assert os.path.exists(method_invoc_query_path), f'Query not found: {method_invoc_query_path}'
    assert os.path.exists(constructor_invoc_query_path), f'Query not found: {constructor_invoc_query_path}'
    method_invocations = []

    for query_path in [method_invoc_query_path, constructor_invoc_query_path]:
        query_run_cmd = [CODEQL_PATH, 'query', 'run', f'--database={database_path}', query_path]

        query_result = subprocess.run(query_run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8')
        query_result = query_result.stdout
        
        for each_line in query_result.strip().split('\n')[2:]:
            infos = each_line.split('|')
            callee_class_name, callee_method_signature, invoker_start_line, invoker_end_line, invoker_file_path, invoker_class_name, invoker_method_signature = infos[1].strip(), infos[2].strip(), infos[3].strip(), infos[4].strip(), infos[5].strip(), infos[6].strip(), infos[7].strip()

            m_invo = MethodInvocation(callee_class_name, callee_method_signature, int(invoker_start_line), int(invoker_end_line), invoker_file_path, invoker_class_name, invoker_method_signature)

            method_invocations.append(m_invo)


    return method_invocations


def extract_method_body(file_path, start_line, end_line):
    with open(file_path, 'r', encoding='utf8') as f:
        lines = f.readlines()
        method_body = ''.join(lines[start_line - 1: end_line])
    return method_body


def integrate(method_declarations, method_invocations):
    knowledge_graph = {}
    for each_m_decl in method_declarations:
        m_decl_name = each_m_decl.method_signature.split('(')[0]
        m_decl_class_name = each_m_decl.class_name
        m_decl_signature = each_m_decl.method_signature
        m_decl_body = extract_method_body(each_m_decl.file_path, each_m_decl.method_start_line, each_m_decl.method_end_line)

        method_info = knowledge_graph.get(m_decl_name, {})
        method_class_info = method_info.get(each_m_decl.class_name, {})
        method_class_sign_info = method_class_info.get(each_m_decl.method_signature, {})
        method_class_sign_info['method_body'] = m_decl_body
        
        invocation_info = []
        for each_m_invo in method_invocations:
            if each_m_invo.callee_class_name == m_decl_class_name and each_m_invo.callee_method_signature == m_decl_signature:
                invocker_body = extract_method_body(each_m_invo.invoker_file_path, each_m_invo.invoker_start_line, each_m_invo.invoker_end_line)
                invocation_info.append((each_m_invo.invoker_file_path, invocker_body))
        method_class_sign_info['invocation_info'] = invocation_info

        method_class_info[each_m_decl.method_signature] = method_class_sign_info
        method_info[each_m_decl.class_name] = method_class_info
        knowledge_graph[m_decl_name] = method_info
    return knowledge_graph


def construct_method_invocation_in_a_method_table(method_invocations):
    method_invoc_table = {}
    for each_m_invo in method_invocations:
        class2methods = method_invoc_table.get(each_m_invo.invoker_class_name, {})
        method2invocations = class2methods.get(each_m_invo.invoker_method_signature, [])
        is_exist = False
        for each_pair in method2invocations:
            if each_pair[0] == each_m_invo.callee_class_name and each_pair[1] == each_m_invo.callee_method_signature:
                is_exist = True
                break
        if not is_exist:
            method2invocations.append((each_m_invo.callee_class_name, each_m_invo.callee_method_signature))

        class2methods[each_m_invo.invoker_method_signature] = method2invocations
        method_invoc_table[each_m_invo.invoker_class_name] = class2methods
    return method_invoc_table


def construct_method_invocation_in_a_file_table(method_invocations):
    method_invoc_table = {}
    for each_m_invo in method_invocations:
        file2invocations = method_invoc_table.get(each_m_invo.invoker_file_path, [])
        is_exist = False
        for each_pair in file2invocations:
            if each_pair[0] == each_m_invo.callee_class_name and each_pair[1] == each_m_invo.callee_method_signature:
                is_exist = True
                break
        if not is_exist:
            file2invocations.append((each_m_invo.callee_class_name, each_m_invo.callee_method_signature))

        method_invoc_table[each_m_invo.invoker_file_path] = file2invocations
    return method_invoc_table


def construct_method_invocation_full_dict(method_invocations):
    full_dict = {}  # {method_name: {class_name: {method_signature}}}
    for each_m_invo in method_invocations:
        callee_class_name = each_m_invo.callee_class_name
        callee_method_signature = each_m_invo.callee_method_signature
        callee_method_name = callee_method_signature.split('(')[0]

        class_info = full_dict.get(callee_method_name, {})
        method_info = class_info.get(callee_class_name, [])
        if callee_method_signature not in method_info:
            method_info.append(callee_method_signature)
        class_info[callee_class_name] = method_info
        full_dict[callee_method_name] = class_info
    return full_dict


def construct_knowledge_graph(configs, referable_test_case_path=None):
    os.makedirs(configs.knowledge_graph_save_dir, exist_ok=True)

    database_path = configs.codeql_database_for_project_path
    java_project_path = configs.project_with_test_file_path
    query_collect_method_declaration_path = configs.codeql_collect_method_declaration_include_outer_path
    query_collect_constructor_declaration_path = configs.codeql_collect_constructor_declaration_include_outer_path
    query_collect_method_invocation_path = configs.query_collect_invocation_path
    query_collect_constructor_invocation_path = configs.codeql_collect_constructor_invocation_moreInfo_include_outer_path
    
    # create database for the target project
    os.makedirs(os.path.dirname(database_path), exist_ok=True)
    is_success = create_database(database_path, java_project_path)
    if not is_success:
        return False

    # collect all method declarations in the project
    method_declarations = collect_method_declarations(database_path, query_collect_method_declaration_path, query_collect_constructor_declaration_path)
    with open(f'{configs.method_declaration_save_path}', 'w', encoding='utf8') as f:
        json.dump([m_decl._asdict() for m_decl in method_declarations], f, indent=4)

    # for each method declaration, search for the method invocation
    if referable_test_case_path is None:
        method_invocations = collect_method_invocations(database_path, query_collect_method_invocation_path, query_collect_constructor_invocation_path)
    else:
        raise NotImplementedError('construct_knowledge_graph with referable_test_case_path set is Not implemented yet.')

    # save the method invocations
    with open(f'{configs.knowledge_graph_save_dir}/method_invocations.json', 'w', encoding='utf8') as f:
        json.dump([m_invo._asdict() for m_invo in method_invocations], f, indent=4)

    # construct the knowledge graph
    knowledge_graph = integrate(method_declarations, method_invocations)
    logger.debug(f'\nsaving knowledge graph (len={len(knowledge_graph)}) in {configs.knowledge_graph_save_path}')
    # TEST
    if len(knowledge_graph) == 0:
        logger.error('No knowledge graph constructed.')
    #
    with open(f'{configs.knowledge_graph_save_path}', 'w', encoding='utf8') as f:
        json.dump(knowledge_graph, f, indent=4)

    method_invocations_in_a_method = construct_method_invocation_in_a_method_table(method_invocations)
    with open(f'{configs.method_invocation_in_a_method_table_save_path}', 'w', encoding='utf8') as f:
        json.dump(method_invocations_in_a_method, f, indent=4)

    method_invocations_in_a_file = construct_method_invocation_in_a_file_table(method_invocations)
    with open(f'{configs.method_invocation_in_a_file_table_save_path}', 'w', encoding='utf8') as f:
        json.dump(method_invocations_in_a_file, f, indent=4)
    
    # construct the full method invocation dict (do not consider whether the method is declared within the project or not)
    full_method_invocation_dict = construct_method_invocation_full_dict(method_invocations)
    with open(f'{configs.full_method_invocation_dict_save_path}', 'w', encoding='utf8') as f:
        json.dump(full_method_invocation_dict, f, indent=4)

    return True


if __name__ == '__main__':
    project_name = 'spark'
    configs = Configs(project_name)
    construct_knowledge_graph(configs)