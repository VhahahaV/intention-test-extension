from user_config import global_config
import os

class Configs:
    def __init__(self, project_name, tester_path = '') -> None:
        self.root_dir = ''
        self.openai_api_key = global_config['openai']['apikey']

        self.project_name = project_name
        self.llm_name = 'gpt-4o'

        self.max_context_len = 1024
        self.max_input_len = 4096
        self.max_num_generated_tokens = 1024
        self.verbose = True

        if tester_path.strip():
            self.workspace = tester_path
        else:
            self.workspace = f'{self.root_dir}/intention_test_extension'

        self.corpus_path =  f'{self.workspace}/data/{project_name}.json'
        self.project_without_test_file_path = f'{self.workspace}/data/repos_removing_test/{project_name}'
        self.project_with_test_file_path = f'{self.workspace}/data/repos_with_test/{project_name}'
        
        self.generation_log_dir = f'{self.workspace}/data/generation_logs/{project_name}'
        self.test_case_running_log_dir = f'{self.workspace}/data/test_case_running_logs/{project_name}'

        self.knowledge_graph_save_dir = f'{self.workspace}/data/knowledge_graphs/{self.project_name}'
        self.knowledge_graph_save_path = f'{self.knowledge_graph_save_dir}/knowledge_graph.json'
        self.method_invocation_in_a_method_table_save_path = f'{self.knowledge_graph_save_dir}/method_invocation_in_a_method_table.json'
        self.method_invocation_in_a_file_table_save_path = f'{self.knowledge_graph_save_dir}/method_invocation_in_a_file_table.json'
        self.full_method_invocation_dict_save_path = f'{self.knowledge_graph_save_dir}/full_method_invocation_dict.json'
        self.method_declaration_save_path = f'{self.knowledge_graph_save_dir}/method_declaration.json'

        self.set_codeql_query_path()

    def is_corpus_prepared(self):
        return os.path.exists(self.corpus_path)

    def set_codeql_query_path(self):
        self.query_method_invocation_in_a_file_template_path = f'{self.workspace}/codeql_query/codeql_analyze_method_invocation_in_a_file_template.ql'
        self.query_method_invocation_in_a_file_impl_path = f'{self.workspace}/codeql_query/codeql_analyze_method_invocation_in_a_file_impl_{self.project_name}.ql'
        self.codeql_analyze_constructor_invocation_in_a_file_template_path = f'{self.workspace}/codeql_query/codeql_analyze_constructor_invocation_in_a_file_template.ql'
        self.query_variable_declaration_in_a_file_template_path = f'{self.workspace}/codeql_query/codeql_analyze_variable_declaration_in_a_file_template.ql'

        self.codeql_database_for_project_path = f'{self.workspace}/data/codeql_dbs/{self.project_name}_project'
        self.codeql_database_for_target_tc_path = f'{self.workspace}/data/codeql_dbs/{self.project_name}_target_tc'

        self.query_collect_declaration_path = f'{self.workspace}/codeql_query/codeql_collect_method_declaration.ql'
        self.query_collect_constructor_declaration_path = f'{self.workspace}/codeql_query/codeql_collect_constructor_declaration.ql'
        self.query_collect_invocation_path = f'{self.workspace}/codeql_query/codeql_collect_method_invocation_moreInfo.ql'
        self.query_collect_invocation_exclude_referable_tc_template_path = f'{self.workspace}/codeql_query/codeql_collect_method_invocation_exclude_referable_tc_template.ql'
        self.query_collect_constructor_invocation_path = f'{self.workspace}/codeql_query/codeql_collect_constructor_invocation_moreInfo.ql'

        self.codeql_collect_method_declaration_include_outer_path = f'{self.workspace}/codeql_query/codeql_collect_method_declaration_include_outer.ql'

        self.codeql_collect_constructor_declaration_include_outer_path = f'{self.workspace}/codeql_query/codeql_collect_constructor_declaration_include_outer.ql'

        self.codeql_collect_constructor_invocation_moreInfo_include_outer_path = f'{self.workspace}/codeql_query/codeql_collect_constructor_invocation_moreInfo_include_outer.ql'