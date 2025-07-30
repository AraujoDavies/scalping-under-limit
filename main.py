import time
import logging
import cv2
import pyautogui
from PIL import Image
import mss
import pygetwindow as gw
import easyocr
from datetime import datetime

import os
import shutil


log = datetime.now().strftime("dia%d%m%y.log")
logging.basicConfig(
    filename=log,
    level=logging.INFO,
    encoding='utf-8',
    format="%(asctime)s - %(levelname)s: %(message)s"
)
# Inicializa o OCR
# reader = easyocr.Reader(['en'], gpu=False)
reader = easyocr.Reader(['pt'], gpu=False)

class Wagertool():
    def __init__(self):
        self.ladder = {} # armazena valores da ladder odd, peso do dinheiro e local de click aproximado
        self.mercado = '' # Mostra qual ladder do mercado está aberta. No caso "Menos de" ou "Mais de"
        self.gap = 10 # Quantos ticks de gap
        self.odds_back = [] # lista odd atual para back + 3 pra cima
        self.odds_lay = [] # lista odd atual para lay + 3 pra baixo
        self.back_eixo_x = 0 # ref para clicar no back
        self.lay_eixo_x = 0 # ref para clicar no lay
        self.centralizar_escada = None # seta coordenadas para centralizar ladder
        self.aovivo = False # verifica se o mercado está aberto

        for janela in gw.getAllTitles():
            if 'ESCADA:' in janela:
                print(f'Trabalhando no mercado: {janela}')
                self.janela = janela
                break

        if os.path.exists('./debug_screen') is False:
            os.mkdir('./debug_screen')

    def captura_tela(self):
        """
            Abre o mercado por enquanto vamos fazer só um mercado e tira print
        """
        if self.janela not in gw.getAllTitles():
            log_msg = f'Janela fechada: {self.janela}'
            logging.warning(log_msg)
            print(log_msg)
            raise RuntimeError('janela fechada!')

        wtool = gw.getWindowsWithTitle(self.janela)[0]

        # Coleta as coordenadas da janela
        left, top, width, height = wtool.left, wtool.top, wtool.width, wtool.height

        # Captura apenas a área da janela usando mss
        with mss.mss() as sct:
            monitor = {
                "left": left,
                "top": top,
                "width": width,
                "height": height
            }
            sct_img = sct.grab(monitor)

        # # Carrega a imagem e faz OCR
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        img.save("captura_janela.png")
        logging.info('capturou imagem do mercado...')


    def extrai_valores(self):
        """
            Analisa imagem capturada e estrutura os dados

            Requisitos:

            - ter '123456789' como valor de stake para identificar o mercado

            - Configuração da escada: altura da linha e tamanho do texto igual a 30
        """
        self.ladder = {} # reseta ladder antes de atualizar
        self.centralizar_escada = None # reseta. Se caso a ladder se movimente

        # Carregar imagem original colorida
        img = cv2.imread("captura_janela.png")

        # Redimensionar para aumentar chance de leitura
        resized = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        # Convertido para escala de cinza
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        # Aumentar contraste com CLAHE (leve)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        contraste = clahe.apply(gray)
        # Usar OCR direto
        logging.info('Analisando imagem...')
        results = reader.readtext(contraste, detail=1, allowlist='0123456789Maisdemenos.,AOVIVOaovivo ')
        logging.info('imagem analisada!')

        # Processa o resultado em dicionário
        img_to_dict = {}

        self.aovivo = False
        for index, result in enumerate(results):
            bbox, text, conf = result
            if 'AO VIVO' in text:
                self.aovivo = True
            # print(text)
            if text == '123456789':
                self.mercado = results[index + 1][1] # diferenciar Scalping Under do Migalha
            
            text = text.strip()
            if not text.replace(".", "", 1).isdigit():
                continue

            # Detecta odds (ex: 1.24)
            if "." in text and text.count(".") == 1 and len(text) <= 5:
                odd = text
                odd_x = (bbox[0][0] + bbox[2][0]) / 2
                odd_y = (bbox[0][1] + bbox[2][1]) / 2

                img_to_dict[odd] = {"back": 0, "lay": 0, "y": odd_y, "x": odd_x}
                if self.centralizar_escada is None:
                    self.centralizar_escada = (odd_x, odd_y)

        # Agora adiciona os valores de apostas à esquerda ou direita
        for bbox, text, conf in results:
            text = text.strip().replace(",", "").replace(" ", "")

            if not text.isdigit():
                continue

            val = int(text)
            val_x = (bbox[0][0] + bbox[2][0]) / 2
            val_y = (bbox[0][1] + bbox[2][1]) / 2

            # Encontra a odd mais próxima na vertical
            closest = None
            min_dist = 20  # tolerância de pixels
            for odd, data in img_to_dict.items():
                if abs(val_y - data["y"]) < min_dist:
                    closest = odd
                    min_dist = abs(val_y - data["y"])

            if closest:
                if val_x < img_to_dict[closest]["x"]:
                    img_to_dict[closest]["back"] += val
                    # tem o if pq pode bugar com o resumo de apostas correspondidas/não correspondidas
                    if self.back_eixo_x == 0: self.back_eixo_x = val_x 
                else:
                    img_to_dict[closest]["lay"] += val
                    # tem o if pq pode bugar com o resumo de apostas correspondidas/não correspondidas
                    if self.lay_eixo_x == 0: self.lay_eixo_x = val_x 

        self.ladder = img_to_dict
    

    def atualiza_informacoes_da_ladder(self):
        """
            atualiza informações importantes para gerenciar futuras estratégias:

            - Back atual + 3 ODDs acima
            - Lay atual +3 ODDs abaixo
            - GAP do mercado

            Returns:

                bool: True se atualização ocorreu com sucesso!
        """
        ladder = self.ladder
        back_atual, lay_atual, self.gap = None, None, 10

        for index, odd in enumerate(ladder.keys()):
            # GAP e Odds back/lay atual
            if ladder[odd]['lay'] == 0 and ladder[odd]['back'] > 0:
                lay_atual = (float(odd), index)

            if ladder[odd]['back'] == 0 and ladder[odd]['lay'] > 0:
                back_atual = (float(odd), index)

                fracao_da_odd = 100
                if back_atual[0] < 2: fracao_da_odd = 1
                if back_atual[0] >= 2 and back_atual[0] < 3: fracao_da_odd = 2
                if back_atual[0] >= 3 and back_atual[0] < 4: fracao_da_odd = 5
                if back_atual[0] >= 4 and back_atual[0] < 6: fracao_da_odd = 10
                if back_atual[0] >= 6 and back_atual[0] < 10: fracao_da_odd = 20
                if back_atual[0] >= 10 and back_atual[0] < 20: fracao_da_odd = 50

                gap = int(((round(lay_atual[0] - back_atual[0], 2)) * 100) / fracao_da_odd) - 1
                logging.info(f"Back @{back_atual[0]}\nLay @{lay_atual[0]}\nGAP de {gap} tick(s)\n----------------")
                back_atual, lay_atual, self.gap = back_atual, lay_atual, gap
                # reduzindo análise para 3 ticks acima e 3 abaixo
                try:
                    self.odds_back = [list(ladder)[back_atual[1] - i] for i in range(4)]
                    self.odds_lay = [list(ladder)[lay_atual[1] + i] for i in range(4)]
                    return True
                except IndexError:
                    logging.warning('Necessário ter no minimo 3 odds em cada resistência de back/lay')
                    return False


    def click_cashout(self):
        try:
            cashout = pyautogui.locateOnScreen('cashout.jpg', confidence=0.8)
            pyautogui.click(cashout) # evitar clicks fora da área certa
            time.sleep(5)
        except:
            return False


    def migalha(self) -> str:
        """
            Estratégia que faz lay over limit

            Requisitos:

                odd menor q 1.20

            Returns:

                str: status do processo
        """
        if 'Mais de' not in self.mercado:
            return f'Estratégia não pode ser feita no mercado: {self.mercado}'

        range_odd = float(self.odds_back[0])
        range_odd = range_odd <= 1.2
        if range_odd is False:
            time.sleep(10)
            self.click_cashout()
            return f'Range de odd fora do Migalha: {self.odds_back[0]} e {self.odds_lay[0]}'

        if self.gap > 1:
            time.sleep(10)
            return f'GAP maior q o esperado: {self.gap}'
        
        # peso do dinheiro por odd 
        peso_dinheiro_back = [self.ladder[odd]['back'] for odd in self.odds_back]
        peso_dinheiro_lay = [self.ladder[odd]['lay'] for odd in self.odds_lay]
        media_dinheiro_back = sum(peso_dinheiro_back) / len(peso_dinheiro_back) - 1
        media_dinheiro_lay = sum(peso_dinheiro_lay) / len(peso_dinheiro_lay) - 1

        # media dinheiro em lay tem q ser maior q 75% da media em back 
        if media_dinheiro_lay > media_dinheiro_back * 0.75:
            if self.gap == 0: # se tiver sem gap checar melhor odd
                primeira_resistencia = peso_dinheiro_back[1]
                if primeira_resistencia < media_dinheiro_back * 0.80:
                    entrada = 1
                else:
                    entrada = 2 # qual odd deixa nossa entrada + segura
                log_msg = f'Migalha sem GAP - Propondo LAY a @{self.odds_lay[entrada]} - {self.janela}'
                odd_migalha = self.odds_lay[entrada]

            elif self.gap == 1: # se tiver gap de 1 tick proponho
                log_msg = f'Migalha com GAP - Propondo LAY a @{self.odds_lay[2]} - {self.janela}'
                odd_migalha = self.odds_lay[2]

            else: 
                return 'ERRO!! Trava GAP'

            # saber se já está proposto...
            if self.ladder[odd_migalha]['back'] > 0 and self.ladder[odd_migalha]['lay'] > 0:
                log_msg = f"Já está proposto no migalha a {odd_migalha}"
                return log_msg

            print(log_msg)
            logging.info(log_msg)
            return odd_migalha

        return 'media dinheiro em back é maior q em lay'


    def scalping_under_acima_2_20(self) -> str:
        """
            Estratégia que fará o scalping no under em back 
             
            Requisitos:
             
                odd entre 6 e 2.20

            Returns:

                str: status do processo
        """
        if 'Menos de' not in self.mercado:
            time.sleep(10)
            return f'Estratégia não pode ser feita no mercado: {self.mercado}'
       
        range_odd = float(self.odds_back[0])
        range_odd = range_odd >= 2.2 and range_odd < 6
        if range_odd is False:
            time.sleep(10)
            self.click_cashout()
            return f'Range de odd fora do Scalping Under Limit: {self.odds_back[0]} e {self.odds_lay[0]}'

        if self.gap > 3:
            time.sleep(10)
            return f'GAP maior q o esperado: {self.gap}'
        
        # peso do dinheiro por odd 
        peso_dinheiro_back = [self.ladder[odd]['back'] for odd in self.odds_back]
        peso_dinheiro_lay = [self.ladder[odd]['lay'] for odd in self.odds_lay]
        media_dinheiro_back = sum(peso_dinheiro_back) / len(peso_dinheiro_back) - 1
        media_dinheiro_lay = sum(peso_dinheiro_lay) / len(peso_dinheiro_lay) - 1

        # analisar o peso do dinheiro do lay para já propor preço no back
        if media_dinheiro_back < media_dinheiro_lay or media_dinheiro_lay > 15000:
            return 'Mercado em lay apresenta resistência!'
        
        # 1° CENÁRIO: primeira odd do lay tem dinheiro e é menor q a média do dinheiro em lay(das 3 odds) dividido por 2 ?
        if peso_dinheiro_lay[1] > 0 and peso_dinheiro_lay[1] < media_dinheiro_lay / 2: 
            # Então proponha um back seguro (corresponde a pelo menos 15% da média do dinheiro em back)
            for i in range(len(peso_dinheiro_back)):
                if peso_dinheiro_back[i] > media_dinheiro_back * 0.15: 
                    log_msg = f'1. Propondo preço a ODD de @{self.odds_back[i]} - {self.janela}'
                    print(log_msg)
                    logging.warning(log_msg)
                    return self.odds_back[i]

        # 2° CENÁRIO: primeira odd do lay vazia E media do dinheiro em back pelo menos 3 vezes maior q lay E as duas últimas odds do back são maiores q 0 ?
        if peso_dinheiro_lay[1] == 0 and media_dinheiro_back > media_dinheiro_lay * 5 and peso_dinheiro_back[-1] > 0 and peso_dinheiro_back[-2] > 0:
            # então proponho em uma odd sem peso de dinheiro
            log_msg = f'2. Propondo preço a ODD de @{self.odds_back[-3]} - {self.janela}'
            print(log_msg)
            logging.warning(log_msg)
            return self.odds_back[-3]

        return 'Não encontrou odd para propor'


    def entrada(self, odd: str, tipo: str):
        """
            Pyautogui atua no mercado

            Args:

                str: odd: em que odd vamos entrar

                str: tipo: 'back' ou 'lay'

            Returns:

                str: status do processo
        """
        if tipo == 'back': eixo_x = self.back_eixo_x / 2
        if tipo == 'lay': eixo_x = self.lay_eixo_x / 2
       
        eixo_y = self.ladder[odd]['y'] / 2

        pyautogui.moveTo(x=eixo_x, y=eixo_y)
        if int(eixo_x) == int(pyautogui.position().x) and int(eixo_y) == int(pyautogui.position().y):
            pyautogui.click() # evitar clicks fora da área certa

        # cancela entradas propostas antes
        if tipo == 'back': pyautogui.press('c')
        if tipo == 'lay': pyautogui.press('z')

        msg = f'Propôs a {odd} - {self.janela}'
        print(msg)
        logging.warning(msg)
        time.sleep(30)


    def centralizar_ladders(self):
        try:
            tickoffset = pyautogui.locateOnScreen('tickoffset.jpg', confidence=0.8)
            # print('TICKOFFSET localizado!')
        except:
            logging.warning('TICKOFFSET desativado!!!')
            return False

        if self.centralizar_escada is not None:
            eixo_x = self.centralizar_escada[0] / 2
            eixo_y = self.centralizar_escada[1] / 2

            pyautogui.moveTo(x=eixo_x, y=eixo_y)
            if int(eixo_x) == int(pyautogui.position().x) and int(eixo_y) == int(pyautogui.position().y):
                pyautogui.click() # evitar clicks fora da área certa
                logging.info('centralizou ladder')
                time.sleep(1)
            else:
                logging.error('Não sincronizou ladder! click fora da área correta')


def rotina(w):
    try:
        w.centralizar_ladders()
    except: 
        pass
    w.captura_tela()
    w.extrai_valores()
    if w.aovivo:
        try:
            atualizou_ladder = w.atualiza_informacoes_da_ladder()
        except TypeError:
            logging.warning('Não foi possível atualizar a ladder')
            atualizou_ladder = False
        
        if atualizou_ladder:
            # direcionar mercado para uma estratégia apenas
            media_odds_ladder = (float(list(self.ladder)[0]) + float(list(self.ladder)[-1])) / 2

            if media_odds_ladder <= 1.3: # migalha
                odd = w.migalha()
                print(f'Migalinha: {odd}')
                if odd == 'media dinheiro em back é maior q em lay':
                    shutil.copy('./captura_janela.png', f'./debug_screen/{datetime.now().strftime("migalha_%d%m_%H%M%S.png")}')
                if odd in w.ladder.keys():
                    w.entrada(odd=odd, tipo='lay')

            elif media_odds_ladder > 2 and media_odds_ladder <= 7: # migalha
                odd = w.scalping_under_acima_2_20()
                print(f'Scalping Under: {odd}')
                if odd in w.ladder.keys():
                    w.entrada(odd=odd, tipo='back')

            else:
                print('Sem estratégia no momento...')
                time.sleep(15)

w = Wagertool()
self = w
# lopping 
while True:
    try:
        rotina(w)
    except Exception as error:
        if "'Wagertool' object has no attribute 'janela'" not in str(error) or "janela fechada!" not in str(error):
            logging.critical(error)
            shutil.copy('./captura_janela.png', f'./debug_screen/{datetime.now().strftime("ERRO_%d%m_%H%M%S.png")}')
        
        time.sleep(5)
        logging.info('procurando nova janela para trabalhar...')
        w = Wagertool()
