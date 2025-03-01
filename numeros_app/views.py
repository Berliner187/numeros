import json
import hashlib

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.views import View
from django.template.loader import render_to_string
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator
# from asgiref.sync import database_sync_to_async
from django.core import signing
from datetime import timedelta
from django.urls import reverse
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode


from .models import *
from .tracer import *
from .utils import *
from .constants import *
from .forms import *

from django.shortcuts import render

import requests


os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

tracer_l = TracerManager(TRACER_FILE)


def index_view(request):
    return render(request, 'index.html')


@method_decorator(login_required, name='dispatch')
class ManageSurveysView(View):
    async def post(self, request):
        if request.method == 'POST':
            try:
                request_from_user = json.loads(request.body)
                question_count = request_from_user['questions']
                text_from_user = request_from_user['text']

                try:
                    print(f"\n\nGEN STAAAART")

                    manage_generate_surveys_text = ManageGenerationSurveys(request, text_from_user, question_count)
                    generated_text = await manage_generate_surveys_text.github_gpt()

                    if generated_text.get('success'):
                        tokens_used = generated_text.get('tokens_used')
                        cleaned_generated_text = generated_text.get('generated_text')
                        print(f"\n\nGEN TEST: {generated_text}")
                        # tracer_l.tracer_charge(
                        #     'ADMIN', request.user.username, ManageSurveysView.post.__name__,
                        #     f"{cleaned_generated_text}")
                    else:
                        return JsonResponse({'error': 'Произошла ошибка :(\nПожалуйста, попробуйте позже'}, status=429)

                except Exception as fail:
                    return JsonResponse({'error': 'Опаньки :(\n\nК сожалению, не удалось составить тест'}, status=400)

                try:
                    print(f"\n\n---- ТОКЕНОВ ИСПОЛЬЗОВАНО: {tokens_used}\n\n")
                    new_survey_id = uuid.uuid4()

                    # Логика сохранения в БД

                    # survey = Survey(
                    #     survey_id=new_survey_id,
                    #     title=cleaned_generated_text['title'],
                    #     id_staff=get_staff_id(request)
                    # )
                    # survey.save_questions(cleaned_generated_text['questions'])
                    # survey.save()
                    #
                    # _tokens_used = TokensUsed(
                    #     id_staff=get_staff_id(request),
                    #     tokens_survey_used=tokens_used
                    # )
                    # _tokens_used.save()

                    tracer_l.tracer_charge(
                        'DB', request.user.username, ManageSurveysView.post.__name__, "success save to DB")

                    return JsonResponse({'survey': cleaned_generated_text, 'survey_id': f"{new_survey_id}"}, status=200)
                except Exception as fail:
                    user = await sync_to_async(str)(request.user.username)
                    tracer_l.tracer_charge(
                        'INFO', user, ManageSurveysView.post.__name__,
                        "error in save to DB", f"{fail}")
                    return JsonResponse(
                        {'error': 'Ошибочка :(\n\nПожалуйста, попробуйте позже'}, status=400)

            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

        return JsonResponse({'error': 'Invalid request method'}, status=400)


class ManageTelegramMessages:
    def __base_send_message(self, payload=None):
        bot_token = TELEGRAM_BOT_TOKEN
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        requests.post(url, json=payload)

    def send_message(self, user_id, message):
        payload = {
            'chat_id': user_id,
            'text': message,
            'parse_mode': 'HTML'
        }

        self.__base_send_message(payload)

    def send_code_to_user(self, telegram_user_id, code):
        message = f"Код для авторизации: <pre><code>{code}</code></pre>\n\n<i>Нажмите, чтобы скопировать</i>"
        self.send_message(telegram_user_id, message)


def hash_data(data):
    data_string = json.dumps(data, sort_keys=True).encode()
    return hashlib.sha256(data_string).hexdigest()


class TelegramAuthManagement:
    @staticmethod
    def auth_user(telegram_auth_data: dict):
        telegram_user_id = telegram_auth_data.get('telegram_user_id')
        phone_number = telegram_auth_data.get('phone_number')
        first_name = telegram_auth_data.get('first_name')
        last_name = telegram_auth_data.get('last_name')
        username = telegram_auth_data.get('username')

        additional_auth = AuthAdditionalUser.objects.filter(id_telegram=int(telegram_user_id)).first()

        user, created = AuthUser.objects.update_or_create(
            phone=phone_number,
            defaults={
                'confirmed_user': True,
                'first_name': first_name,
                'last_name': last_name,
                'username': username if username is not None else telegram_user_id,
                'email': None
            }
        )

        if not additional_auth:
            new_auth_telegram = AuthAdditionalUser.objects.create(
                user=user,
                id_telegram=int(telegram_user_id),
            )
            new_auth_telegram.save()

            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'confirm_user',
                f"Created additional auth for user: {telegram_user_id}")

            plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
            subscription = Subscription.objects.create(
                staff_id=user.id_staff,
                plan_name=plan_name,
                end_date=end_date,
                status=status,
                billing_cycle=billing_cycle,
                discount=0.00
            )
            subscription.save()

        return user

    @staticmethod
    def one_click_auth(telegram_user_id: int, first_name: str, last_name: str, username: str):
        """
            Авторизация пользователя по telegram_user_id.
            Если пользователь уже есть в системе, привязывает telegram_user_id к его аккаунту.
            Если пользователя нет, создаёт новую запись.
        """
        additional_auth = AuthAdditionalUser.objects.filter(id_telegram=int(telegram_user_id)).first()

        if additional_auth:
            user = additional_auth.user
            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'one_click_auth',
                f"User already linked: {telegram_user_id}")
            return user

        user = AuthUser.objects.filter(phone__isnull=False).first()

        if user:
            # Если пользователь найден, идет привязка telegram_id к существующему аккаунту
            new_auth_telegram = AuthAdditionalUser.objects.create(
                user=user,
                id_telegram=int(telegram_user_id),
            )
            new_auth_telegram.save()

            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'one_click_auth',
                f"Linked existing user: {telegram_user_id} to phone: {user.phone}")
        else:
            # Если пользователь не найден, идет создание нового
            user = AuthUser.objects.create(
                first_name=first_name,
                last_name=last_name,
                username=username if username is not None else str(telegram_user_id),
                email=None
            )
            user.save()

            new_auth_telegram = AuthAdditionalUser.objects.create(
                user=user,
                id_telegram=int(telegram_user_id),
            )
            new_auth_telegram.save()

            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'one_click_auth',
                f"Created new user: {telegram_user_id}")

            plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
            subscription = Subscription.objects.create(
                staff_id=user.id_staff,
                plan_name=plan_name,
                end_date=end_date,
                status=status,
                billing_cycle=billing_cycle,
                discount=0.00
            )
            subscription.save()

        return user


@csrf_exempt
def one_click_auth_view(request, token: str, token_hash: str):
    """
        Обработка одноразовой ссылки для авторизации через Telegram.
    """
    if request.user.is_authenticated:
        return redirect('create')

    try:
        expected_hash = hashlib.sha256(token.encode()).hexdigest()
        if expected_hash != token_hash:
            return JsonResponse({"status": "error", "message": "Invalid token hash"}, status=400)

        parts = token.split(':')
        if len(parts) != 3:
            return JsonResponse({"status": "error", "message": "Invalid token format"}, status=400)

        telegram_user_id, timestamp, _ = parts
        telegram_user_id = int(telegram_user_id)
        timestamp = int(timestamp)

        current_time = int(time.time())
        if current_time - timestamp > 300:
            return JsonResponse({"status": "error", "message": "Link expired"}, status=400)

        user = TelegramAuthManagement.one_click_auth(
            telegram_user_id=telegram_user_id,
            first_name="",
            last_name="",
            username=f"{telegram_user_id}"
        )

        tracer_l.tracer_charge(
            'ADMIN', f"telegram_id {telegram_user_id}",
            'one_click_auth_view',
            f"User authorized via one-click link: {telegram_user_id}")

        login(request, user)
        request.session['user_id'] = user.id

        return redirect('create')

    except Exception as fail:
        tracer_l.tracer_charge(
            'ERROR', 'one_click_auth_view',
            'one_click_auth_view',
            f"Error: {fail}")
        return JsonResponse({"status": "error", "message": f"Error: {fail}"}, status=500)


user_verify_code = {}


@csrf_exempt
def confirm_user(request):
    """ Прием данных с сервера V1, дешифровка и создание аккаунта для нового пользователя """
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

        data = body.get('data')
        data_hash = body.get('data_hash')

        if hash_data(data) != data_hash:
            return JsonResponse({'status': 'error', 'message': 'Data integrity check failed'}, status=402)

        telegram_user_id = data.get('telegram_user_id')
        phone_number = str(data.get('phone_number'))
        username = data.get('username') or ''
        first_name = data.get('first_name')
        last_name = data.get('last_name') or ''

        tracer_l.tracer_charge(
            'ADMIN', get_client_ip(request),
            'confirm_user',
            f"Success auth: hash is OK for {first_name} {username}")

        telegram_auth_data = {
            'telegram_user_id': telegram_user_id,
            'phone_number': phone_number,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
        }
        user = TelegramAuthManagement.auth_user(telegram_auth_data)

        login(request, user)
        request.session['user_id'] = user.id

        return JsonResponse({'status': 'success', 'user_id': user.id})

    return JsonResponse({'status': 'error', 'message': 'Invalid response'}, status=400)


@login_required
def create_payment(request):
    user_data = get_object_or_404(AuthUser, id_staff=get_staff_id(request))

    order_id = generate_payment_id()

    context = {
        'page_title': 'Выбор тарифного плана',
        'username': get_username(request),
        'email': '' if user_data.email is None else user_data.email,
        'phone': '' if user_data.phone is None else user_data.phone,
        'order_id': order_id,
        'fullname': user_data.username,
    }

    return render(request, 'payments/payment.html', context)


class PaymentInitiateView(View):
    """
        Вьюшка инициализации платежа.
    """
    def post(self, request):
        data = json.loads(request.body)
        # Извлечение данных из запроса
        amount = data['amount']
        description = data['description']
        order_id = data['orderId']
        email = data['email']
        phone = data['phone']
        receipt = data['receipt']

        print(phone, email)
        print("amount", amount)

        plan_prices = {
            'Начальный': 0,
            'Стандартный': 220,
            'Премиум': 590,
            'Ультра': 990
        }

        if int(amount) != plan_prices.get(description):
            return JsonResponse({'Success': False, 'Message': 'Неверная сумма.'}, status=400)

        order_id = generate_payment_id()
        print('приход', order_id)

        items = [
            {
                "Name": "Премиум план",
                "Price": int(amount) * 100,
                "Quantity": 1,
                "Amount": int(amount) * 100,
                "Tax": "none"
            },
        ]

        total_amount = sum(item['Amount'] for item in items)

        data_token = [
            {"TerminalKey": TERMINAL_KEY},
            {"Amount": str(total_amount)},
            {"OrderId": order_id},
            {"Description": description},
            {"Password": TERMINAL_PASSWORD}
        ]

        created_token = PaymentManager().generate_token_for_new_payment(data_token)

        request_body = {
            "TerminalKey": TERMINAL_KEY,
            "Amount": total_amount,
            "OrderId": order_id,
            "Description": description,
            "Token": created_token,
            "DATA": {
                "Phone": phone,
                "Email": email
            },
            "Receipt": {
                "Email": email,
                "Phone": phone,
                "Taxation": "osn",
                "Items": items
            }
        }

        headers = {"Content-Type": "application/json"}
        response = requests.post("https://securepay.tinkoff.ru/v2/Init/", json=request_body, headers=headers)
        response_data = response.json()

        print()
        for key, value in response_data.items():
            print(key, value)
        print()

        if response_data.get('Success'):
            subscription_obj = Subscription.objects.filter(staff_id=get_staff_id(request))
            if subscription_obj.exists():
                subscription_obj.delete()

            # TODO: Сделать как транзакцию
            # Инициализация тарифного плана
            subscription = Subscription.objects.create(
                staff_id=get_staff_id(request),
                plan_name=description,
                end_date=datetime.now() + timedelta(days=30),
                status='inactive',
                billing_cycle='monthly',
                discount=0.00
            )
            subscription.save()
            # Инициализация оплаты
            new_payment = Payment.objects.create(
                staff_id=get_staff_id(request),
                payment_id=response_data.get('PaymentId'),
                subscription=subscription,
                order_id=order_id,
                amount=int(amount) * 100,
                status='pending'
            )
            new_payment.save()

            # Запись в транзакции
            new_trans = TransactionTracker.objects.create(
                staff_id=get_staff_id(request),
                payment_id=response_data.get('PaymentId'),
                description=description,
                order_id=order_id,
                amount=int(amount) * 100,
            )
            new_trans.save()

            return JsonResponse({
                'Success': True,
                'PaymentURL': response_data['PaymentURL'],
                'Message': 'Платеж успешно инициирован.'
            })
        else:
            return JsonResponse({
                'Success': False,
                'ErrorCode': response_data.get('ErrorCode'),
                'Message': response_data.get('Message')
            }, status=400)


def get_payment_data(status, description, plan_name, end_date, payment_id, order_id, amount):
    _payment_data = {
        "payment_status": status, "text_status": description, "plan_name": plan_name,
        "plan_end_date": end_date, "payment_id": payment_id, 'order_id': order_id, 'amount': amount
    }
    return _payment_data


class PaymentSuccessView(View):
    def get(self, request):
        success = request.GET.get('Success')
        error_code = request.GET.get('ErrorCode')
        payment_id = request.GET.get('PaymentId')
        amount = request.GET.get('Amount')

        if success == 'true' and error_code == '0':
            try:
                payment = Payment.objects.get(payment_id=payment_id)
                subscription = Subscription.objects.get(staff_id=get_staff_id(request))

                payment_manager = PaymentManager()
                payment_parameters = [payment.order_id, TERMINAL_PASSWORD, TERMINAL_KEY]
                payment_status = payment_manager.check_order(payment_parameters)['response']['Payments'][0]['Status']

                if subscription.status == 'active' and payment.status == 'completed':
                    return redirect('create')

                description_payment = PAYMENT_STATUSES.get(payment_status, 'Статус не найден')

                error_payment_data = get_payment_data(
                    "Неудача", description_payment, subscription.plan_name, subscription.end_date,
                    payment.payment_id, payment.order_id, payment.amount
                )

                if int(payment.amount) != int(amount):
                    return render(request, 'payments/pay_status.html', error_payment_data)

                elif payment_status == 'DEADLINE_EXPIRED':
                    print("Срок действия платежа истек.")
                    return render(request, 'payments/pay_status.html', error_payment_data)

                elif payment_status == 'CONFIRMED':
                    payment.status = 'completed'
                    payment.save()

                    subscription.start_date = datetime.now()
                    subscription.status = 'active'
                    subscription.save()

                    formatted_amount = f"{payment.amount / 100:,.2f}".replace(',', ' ').replace('.', ',') + " RUB"

                    payment_details = [
                        {"label": "Сумма", "value": formatted_amount},
                        {"label": "ID платежа", "value": payment.payment_id},
                        {"label": "ID заказа", "value": payment.order_id},
                        {"label": "Заканчивается", "value": get_formate_date(subscription.end_date)},
                    ]

                    payment_data = {
                        "page_title": "Успешный платеж",
                        "payment_status": "Успешно",
                        "text_status": "Спасибо за покупку!",
                        "plan_name": subscription.get_human_plan(),
                        "payment_details": payment_details,
                        "username": get_username(request)
                    }

                    # Запись в транзакции
                    new_transaction = TransactionTracker.objects.create(
                        staff_id=get_staff_id(request),
                        payment_id=payment.payment_id,
                        description=f'{formatted_amount}, {subscription.get_human_plan()}, completed: {payment_status}',
                        order_id=payment.order_id,
                        amount=int(amount),
                    )
                    new_transaction.save()

                    try:
                        payment_details_text = "\n".join(
                            [f"<b>{detail['label']}:</b> {detail['value']}" for detail in payment_details])

                        message = (
                            f"{CONFIRM_SYMBOL} Успешный платеж\n\n"
                            f"<b>Статус платежа:</b> {payment_data['payment_status']}\n"
                            f"<b>План:</b> {payment_data['plan_name']}\n\n"
                            f"<b>Детали платежа:</b>\n"
                            f"{payment_details_text}\n\n"
                            f"<b>ID пользователя:</b> {get_staff_id(request)}"
                        )

                        auth_user = AuthUser.objects.get(id_staff=get_staff_id(request))
                        additional_auth_user = AuthAdditionalUser.objects.get(user=auth_user)

                        telegram_message_manager = ManageTelegramMessages()
                        telegram_message_manager.send_message(TELEGRAM_CHAT_ID, message)
                        telegram_message_manager.send_message(additional_auth_user.id_telegram, message)

                    except Exception as fail:
                        tracer_l.tracer_charge(
                            'INFO', f"{get_username(request)}",
                            PaymentSuccessView.__name__,
                            f'Fail while send info about payment to Telegram', fail)

                    return render(request, 'payments/pay_status.html', payment_data)
                else:
                    print("Статус платежа: ", payment_status)
                    return render(request, 'payments/pay_status.html', error_payment_data)
            except Payment.DoesNotExist:
                error_payment_data = {
                    "page_title": "Ошибка оплаты",
                    "payment_status": "Неудача",
                    "text_status": "Платеж не существует",
                }
                return render(request, 'payments/pay_status.html', error_payment_data)
        else:
            subscription = Subscription.objects.get(staff_id=get_staff_id(request))

            payment_data = {
                "payment_status": "Не удалось", "page_title": "Ошибка при оплате",
                "text_status": "К сожалению, не удалось активировать план :(",
                "plan_name": subscription.get_human_plan(),
            }
            return render(request, 'payments/pay_status.html', payment_data)


@csrf_exempt
def phone_number_view(request):
    if request.method == 'POST':
        form = PhoneNumberForm(request.POST)

        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']

            user = AuthUser.objects.filter(phone=phone_number).first()
            new_auth_telegram = AuthAdditionalUser.objects.filter(user=user).first()

            if new_auth_telegram and (user.confirmed_user is True):
                code = random.randint(10000, 99999)
                user_verify_code[user.phone] = code

                telegram_message_manager = ManageTelegramMessages()
                telegram_message_manager.send_code_to_user(new_auth_telegram.id_telegram, code)

                tracer_l.tracer_charge(
                    'ADMIN', get_client_ip(request),
                    'phone_number_view',
                    f"phone_number_view: {user.id}, {code}")

                request.session['phone_number'] = phone_number
                return JsonResponse({'status': 'success', 'message': 'Код отправлен'})
            else:
                referral_link = f"https://t.me/zverbotishe_bot/"

                return JsonResponse({
                    'status': 'success',
                    'message': 'phone init',
                    'referral_link': referral_link,
                })

    else:
        form = PhoneNumberForm()

    return render(request, 'phone_number_form.html', {'form': form, 'code_form': False})


@csrf_exempt
def verify_code_view(request):
    if request.method == 'POST':
        verification_code = request.POST.get('verification_code')
        phone_number = request.session.get('phone_number')

        user = AuthUser.objects.filter(phone=phone_number).first()

        if user:
            if user_verify_code.get(user.phone) == int(verification_code):
                tracer_l.tracer_charge(
                    'ADMIN', get_client_ip(request),
                    'phone_number_view',
                    f"3 verify_code_view: {user.id} {user.username}")

                login(request, user)
                request.session['user_id'] = user.id

                return redirect('create')

            else:
                return JsonResponse({'status': 'error', 'message': 'Неверный код'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Пользователь не найден'})

    tracer_l.tracer_charge(
        'ADMIN', get_client_ip(request),
        'phone_number_view',
        f"2 verify_code_view: {get_username(request)} Неверный запрос")
    return JsonResponse({'status': 'error', 'message': 'Неверный запрос'})
