import json
import datetime
import random
import string
from datetime import timedelta
import locale
import os
import re
import time
import hashlib

from django.http import JsonResponse

import openai
import requests
import httpx
import asyncio

from .tracer import *


tracer_l = TracerManager(TRACER_FILE)


load_env(os.path.join(os.path.dirname(__file__), '.env'))


OPENAI_TOKEN = os.getenv("OPENAI_TOKEN")


def init_free_subscription():
    plan_name = 'Стартовый'
    end_date = datetime.now() + timedelta(days=7)
    status = 'active'
    billing_cycle = 'weakly'
    discount = 0.00
    return plan_name, end_date, status, billing_cycle, discount


class ManageGenerationSurveys:
    def __init__(self, request):
        self.request = request

    @staticmethod
    async def github_gpt() -> dict:
        client = openai.OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=OPENAI_TOKEN,
        )
        # try:
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            messages=[
                {
                    "role": "system",
                    "content": 'ПРОМПТ 01',
                },
                {
                    "role": "user",
                    "content": f"ПРОМПТ 02",
                }
            ],
            model="gpt-4o",
            temperature=.3,
            max_tokens=2048,
            top_p=1
        )

        # try:
        generated_text = completion.choices[0].message.content
        print("\n\ngenerated_text", generated_text)
        cleaned_generated_text = generated_text.replace("json", "").replace("`", "")
        tokens_used = completion.usage.total_tokens

        print("\n\ncleaned_generated_text", cleaned_generated_text)
        return {
            'success': True, 'generated_text': json.loads(cleaned_generated_text), 'tokens_used': tokens_used
        }


def get_year_now():
    return datetime.now().strftime("%Y")


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_staff_id(request):
    user = request.user
    if user.is_authenticated:
        return user.id_staff
    return None


class PaymentManager:
    def __init__(self):
        pass

    def _post_requests_to_bank(self, request_url, data_json: dict):
        """
            Базовый метод запроса к банку
        """
        headers = {"Content-Type": "application/json"}
        start_time = time.time()
        response_api = requests.post(request_url, json=data_json, headers=headers)
        elapsed_time = time.time() - start_time
        try:
            response = response_api.json()
            if response['Success']:
                return {'success': True, 'response': response, 'elapsed_time': elapsed_time}
            return {
                'success': False, 'response': response, 'code': response_api.status_code,
                'text': response_api.text, 'elapsed_time': elapsed_time
            }
        except Exception as fail:
            return {'success': False, 'response': response_api, 'error': fail}

    @staticmethod
    def generate_token_for_new_payment(data_order):
        """ Генерация токена для инициализации заказа """
        sorted_data = sorted(data_order, key=lambda x: list(x.keys())[0])
        concatenated = ''.join([list(item.values())[0] for item in sorted_data])
        return hashlib.sha256(concatenated.encode('utf-8')).hexdigest()

    def create_payment(self):
        return

    def _generate_token_for_check_order(self, parameters: list):
        """
            Генерация токена для проверки заказа.
            Передается в таком порядке: {OrderId}{Password}{TerminalKey}.
            Прим.: order_data = ["OrderId", "Password", "TerminalKey"]
        """
        concatenated = ''.join([item for item in parameters])
        return hashlib.sha256(concatenated.encode('utf-8')).hexdigest()

    def check_order(self, parameters: list):
        """ Проверка платежа """
        request_url = "https://securepay.tinkoff.ru/v2/CheckOrder"

        post_request = {
            "TerminalKey": TERMINAL_KEY,
            "OrderId": parameters[0],
            "Token": self._generate_token_for_check_order(parameters)
        }

        return self._post_requests_to_bank(request_url, post_request)
