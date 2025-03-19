import re
import torch
from nltk.corpus import stopwords
from typing import List
from rank_bm25 import BM25Okapi
from transformers import AutoModel, AutoTokenizer


class Retriever():
    def __init__(self, corpus_fm: List[str], corpus_fm_name: List[str], corpus_tc: List[str], corpus_tc_name: List[str], corpus_test_case_path) -> None:
        super().__init__()
        self.top_k_fm = 30  # TODO: obtain the statistics of test cases responsible for the same focal method
        self.embedding_model = AutoModel.from_pretrained("Salesforce/codet5p-110m-embedding", trust_remote_code=True).to('cuda')
        self.tokenizer = AutoTokenizer.from_pretrained("Salesforce/codet5p-110m-embedding", trust_remote_code=True)
        self.corpus_fm = corpus_fm
        self.corpus_fm_name = corpus_fm_name
        self.corpus_tc = corpus_tc
        self.corpus_tc_name = corpus_tc_name
        self.corpus_test_case_path = corpus_test_case_path
        self.corpus_tc_name_base = [self.tc_name_embedding(tc_name) for tc_name in corpus_tc_name]
        self.corpus_fm_base = [self.preprocess_code(doc) for doc in corpus_fm]
        self.bm25_fm = BM25Okapi(self.corpus_fm_base)

    def retrieve_v2(self, target_fm: str, target_tc_name, top_k: int = 3, mode: str = 'fm'):  # TODO remove argument 'mode'
        target_fm_proc = self.preprocess_code(target_fm)
        bm25_scores = self.bm25_fm.get_scores(target_fm_proc)
        
        # normalize using min-max normalization
        min_bm25_scores, max_bm25_scores = min(bm25_scores), max(bm25_scores)
        bm25_scores = [(s - min_bm25_scores) / (max_bm25_scores - min_bm25_scores) for s in bm25_scores]

        # get the similarity between the target test case name and the test case names 
        target_tc_name_embedding = self.tc_name_embedding(target_tc_name)
        tc_name_similarities = [torch.cosine_similarity(target_tc_name_embedding, candidate_tc_name_embedding, dim=0).item() for candidate_tc_name_embedding in self.corpus_tc_name_base]

        # combine the scores of focal methods and the similarities of test case names
        combined_scores = [bm25_scores[i] + tc_name_similarities[i] for i in range(len(bm25_scores))]
        top_k_indices = sorted(range(len(combined_scores)), key=lambda i: combined_scores[i], reverse=True)[:top_k]

        # check
        for i in top_k_indices:
            assert self.corpus_tc_name[i] in self.corpus_tc[i]

        return [self.corpus_fm[i] for i in top_k_indices], [self.corpus_fm_name[i] for i in top_k_indices], [self.corpus_tc[i] for i in top_k_indices], [self.corpus_tc_name[i] for i in top_k_indices], [combined_scores[i] for i in top_k_indices], [self.corpus_test_case_path[i] for i in top_k_indices]
    
    def preprocess_code(self, code):
        # Tokenize the code
        tokens = re.split(r'\W+', code)
        
        # Convert tokens to lowercase
        tokens = [token.lower() for token in tokens]
        
        # Remove stop words
        stop_words = set(stopwords.words('english'))
        custom_stop_words = set(['public', 'private', 'protected', 'void', 'int', 'double', 'float', 'string', 'package', 'junit', 'assert', 'import', 'class', 'cn', 'org'])
        filtered_tokens = [token for token in tokens if token not in stop_words and token not in custom_stop_words]
        filtered_tokens = [token for token in filtered_tokens if len(token) > 1]
        return filtered_tokens
    
    def tc_name_embedding(self, tc_name):
        inputs = self.tokenizer.encode(tc_name, return_tensors="pt").to("cuda")
        embedding = self.embedding_model(inputs)[0]
        return embedding
