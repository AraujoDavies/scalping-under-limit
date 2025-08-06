import logging
import os
import shutil
import time
import warnings
from datetime import datetime

import cv2
import easyocr
import mss
import pyautogui
import pygetwindow as gw
from PIL import Image


warnings.filterwarnings(
    "ignore",
    message="'pin_memory' argument is set as true but no accelerator is found.*"
)

log = datetime.now().strftime("dia%d%m%y.log")
logging.basicConfig(
    filename=log,
    level=logging.INFO,
    encoding="utf-8",
    format="%(asctime)s - %(levelname)s: %(message)s",
)
# Inicializa o OCR
# reader = easyocr.Reader(['en'], gpu=False)
reader = easyocr.Reader(["pt"], gpu=False)


class Wagertool:
    def __init__(self):
        self.ladder = (
            {}
        )  # armazena valores da ladder odd, peso do dinheiro e local de click aproximado
        self.gap = 10  # Quantos ticks de gap
        self.odds_back = []  # lista odd atual para back + 3 pra cima
        self.odds_lay = []  # lista odd atual para lay + 3 pra baixo
        self.back_eixo_x = 0  # ref para clicar no back
        self.lay_eixo_x = 0  # ref para clicar no lay

        self.janelas = [] # armazena todas ladders abertas
        if os.path.exists("./debug_screen") is False:
            os.mkdir("./debug_screen")

        if os.path.exists("./entradas") is False:
            os.mkdir("./entradas")



    def atualizar_qt_janelas(self):
        for janela in gw.getAllTitles():
            if "ESCADA: Mais/Menos de" in janela:
                if janela not in self.janelas:
                    print(f"Abriu mercado: {janela}")
                    input('>>>>>>> Teste tickoffset e pressione ENTER')
                    self.janelas.append(janela)
                    self.atualizar_qt_janelas()


    def captura_janela(self, janela: str) -> bool:
        """
            Tira print de quantas ladders estiverem abertas.

            Args:
                str: title da janela

            Returns:

                bool: Se o print foi tirado com sucesso ou não.

        """
        if janela not in gw.getAllTitles():
            self.janelas.remove(janela) # remove do processo
            print(f'Está ladder foi fechada!')
            return False
     
        wtool = gw.getWindowsWithTitle(janela)[0]
        try:
            wtool.activate()
        except:
            print('Falha ao abrir janela')
            time.sleep(5)
            return False

        pyautogui.press('l')
        # coordenadas da janela

        # Captura apenas a área da janela usando mss
        with mss.mss() as sct:
            monitor = {"left": wtool.left, "top": wtool.top, "width": wtool.width, "height": wtool.height}
            sct_img = sct.grab(monitor)

        # # Carrega a imagem e faz OCR
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        img.save("./imgs/captura_janela.png")
        print(f"capturou imagem da ladder...")
        return True


    def extrai_valores(self):
        """
        Analisa imagem capturada e estrutura os dados

        Requisitos:

        - ter '123456789' como valor de stake para identificar o mercado

        - Configuração da escada: altura da linha e tamanho do texto igual a 30
        """
        self.ladder = {'info': {}, 'odd': {}}  # reseta ladder antes de atualizar os resultados
        self.ladder['info']['status'] = "DESCONHECIDO" # "AO VIVO", "FECHADO", "SUSPENSO", 

        # Carregar imagem original colorida
        img = cv2.imread("./imgs/captura_janela.png")

        # ajuste tamanho - sem resize 6s
        img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC) # 16s note 7s no PC
        # Convertido para escala de cinza
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Aumentar contraste com CLAHE (leve)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contraste = clahe.apply(gray)
        # Usar OCR direto
        # logging.info("Analisando imagem...")
        letras_foco = '0123456789 MaisMenosdeCashOut.,-MenuAOVIVOFECHADOSUSPENSOCONTRAWagertool'
        allowlist = ''
        for letra in letras_foco:
            if letra not in allowlist:
                allowlist += letra
        self.results = reader.readtext(
            contraste, detail=1, allowlist=allowlist
        )
        # logging.info("imagem analisada!")

        for index, result in enumerate(self.results):
            bbox, text, conf = result
            if "AO VIVO" in text or "FECHADO" in text or "SUSPENSO" in text:
                self.ladder['info']['status'] = text
            # print(text)
            if text == "123456789":
                self.ladder['info']['mercado'] = self.results[index + 1][
                    1
                ]  # Mais ou Menos... diferenciar Scalping Under do Migalha 

            text = text.strip()
            if not text.replace(".", "", 1).isdigit():
                continue

            # Detecta odds (ex: 1.24)
            if "." in text and text.count(".") == 1 and len(text) <= 5:
                odd = text
                odd_x = (bbox[0][0] + bbox[2][0]) / 2
                odd_y = (bbox[0][1] + bbox[2][1]) / 2

                self.ladder['odd'][odd] = {"back": 0, "lay": 0, "y": odd_y, "x": odd_x}

        # Agora adiciona os valores de apostas à esquerda ou direita
        str_results = ''
        for bbox, text, conf in self.results:
            str_results += text
            text = text.strip().replace(",", "").replace(" ", "")

            if not text.isdigit():
                continue

            val = int(text)
            val_x = (bbox[0][0] + bbox[2][0]) / 2
            val_y = (bbox[0][1] + bbox[2][1]) / 2

            # Encontra a odd mais próxima na vertical
            closest = None
            min_dist = 20  # tolerância de pixels
            for odd, data in self.ladder['odd'].items():
                if abs(val_y - data["y"]) < min_dist:
                    closest = odd
                    min_dist = abs(val_y - data["y"])

            if closest:
                if val_x < self.ladder['odd'][closest]["x"]:
                    self.ladder['odd'][closest]["back"] += val
                    # tem o if pq pode bugar com o resumo de apostas correspondidas/não correspondidas
                    if self.back_eixo_x == 0:
                        self.back_eixo_x = val_x
                else:
                    self.ladder['odd'][closest]["lay"] += val
                    # tem o if pq pode bugar com o resumo de apostas correspondidas/não correspondidas
                    if self.lay_eixo_x == 0:
                        self.lay_eixo_x = val_x

        txt = str_results.replace(' ', '')
        # reecheck peso do dinheiro BACK - quebra de linha do OCR pode prejudicar análise
        odds_txt = txt.split('CONTRA')[1].split('Wa')[0]
        # já aconteceu de confundir 0 -> O virgula -> espaço
        odds_txt = odds_txt.replace('O', '0').replace(',', '')
        odd_anterior = 'abc'
        for index, odd in enumerate(self.ladder['odd']):
            # if odd == '1.16': 
            #     self.ladder['odd'][odd]['back'] = 1
            if self.ladder['odd'][odd]['back'] > 0 and self.ladder['odd'][odd]['lay'] == 0:
                try:
                    peso_back = int(self.ladder['odd'][odd]['back'])
                    check_peso = int(odds_txt.split(odd)[0].split(odd_anterior)[-1])
                    if peso_back != check_peso:
                        diff = check_peso - peso_back
                        if diff < 90000:
                            self.ladder['odd'][odd]['back'] = check_peso
                            print(f'odd back: {odd} - peso do dinheiro: {peso_back} -> {check_peso}')
                        else:
                            print(f'odd back: {odd} - diff assustadora(talvez esteja proposto), mantemos o valor inicial: {peso_back} | valor sugerido: {check_peso}')
                except:
                    print('ERRO de rechecagem no back... IMAGEM SALVA PARA DEBUG')
                    shutil.copy('./imgs/captura_janela.png', f'./debug_screen/{datetime.now().strftime("erro_peso_din_back_%d%m_%H%M%S.png")}')
                    self.ladder = {'info': {}, 'odd': {}}  # reseta ladder para nao retornar nada
            odd_anterior = odd

        # reecheck peso do dinheiro LAY - quebra de linha do OCR pode prejudicar análise
        odd_anterior = 'abc'
        for index, odd in enumerate(self.ladder['odd'].__reversed__()):
            # if odd == '1.10': 
            #     self.ladder['odd'][odd]['lay'] = 1
            if self.ladder['odd'][odd]['lay'] > 0 and self.ladder['odd'][odd]['back'] == 0:
                try:
                    peso_lay = int(self.ladder['odd'][odd]['lay'])
                    check_peso = int(odds_txt.split(odd)[-1].split(odd_anterior)[0])
                    if peso_lay != check_peso:
                        diff = check_peso - peso_back
                        if diff < 90000: 
                            self.ladder['odd'][odd]['lay'] = check_peso
                            print(f'odd lay: {odd} - peso do dinheiro: {peso_lay} -> {check_peso}')
                        else: 
                            print(f'odd lay: {odd} - diff assustadora(talvez esteja proposto), mantemos o valor inicial: {peso_lay} | valor sugerido: {check_peso}')
                except:
                    print('ERRO de rechecagem no lay... IMAGEM SALVA PARA DEBUG')
                    shutil.copy('./imgs/captura_janela.png', f'./debug_screen/{datetime.now().strftime("erro_peso_din_lay_%d%m_%H%M%S.png")}')
                    self.ladder = {'info': {}, 'odd': {}}  # reseta ladder para nao retornar nada
            odd_anterior = odd


    def atualiza_informacoes_da_ladder(self):
        """
        atualiza informações importantes para gerenciar futuras estratégias:

        - Back atual + 3 ODDs acima
        - Lay atual +3 ODDs abaixo
        - GAP do mercado

        Returns:

            bool: True se atualização ocorreu com sucesso!
        """
        ladder = self.ladder['odd']
        back_atual, lay_atual, self.gap = None, None, 10

        for index, odd in enumerate(ladder.keys()):
            # GAP e Odds back/lay atual
            if ladder[odd]["lay"] == 0 and ladder[odd]["back"] > 0:
                lay_atual = (float(odd), index)

            if ladder[odd]["back"] == 0 and ladder[odd]["lay"] > 0:
                back_atual = (float(odd), index)

                fracao_da_odd = 100
                if back_atual[0] < 2:
                    fracao_da_odd = 1
                if back_atual[0] >= 2 and back_atual[0] < 3:
                    fracao_da_odd = 2
                if back_atual[0] >= 3 and back_atual[0] < 4:
                    fracao_da_odd = 5
                if back_atual[0] >= 4 and back_atual[0] < 6:
                    fracao_da_odd = 10
                if back_atual[0] >= 6 and back_atual[0] < 10:
                    fracao_da_odd = 20
                if back_atual[0] >= 10 and back_atual[0] < 20:
                    fracao_da_odd = 50

                gap = (
                    int(
                        ((round(lay_atual[0] - back_atual[0], 2)) * 100) / fracao_da_odd
                    )
                    - 1
                )
                # print(f"Back @{back_atual[0]} | Lay @{lay_atual[0]} |GAP de {gap} tick(s)\n----------------")
                back_atual, lay_atual, self.gap = back_atual, lay_atual, gap
                # reduzindo análise para 3 ticks acima e 3 abaixo
                try:
                    self.odds_back = [list(ladder)[back_atual[1] - i] for i in range(4)]
                    self.odds_lay = [list(ladder)[lay_atual[1] + i] for i in range(4)]
                    return True
                except IndexError:
                    print("Necessário ter no minimo 3 odds em cada resistência de back/lay")
                    return False


    def entrada(self, odd: str, tipo: str):
        """
        Pyautogui atua no mercado

        Args:

            str: odd: em que odd vamos entrar

            str: tipo: 'back' ou 'lay'

        """
        if tipo == "back":
            eixo_x = self.back_eixo_x / 2
        if tipo == "lay":
            eixo_x = self.lay_eixo_x / 2

        eixo_y = self.ladder['odd'][odd]["y"] / 2

        pyautogui.moveTo(x=eixo_x, y=eixo_y)
        if int(eixo_x) == int(pyautogui.position().x) and int(eixo_y) == int(
            pyautogui.position().y
        ):
            pyautogui.click()  # evitar clicks fora da área certa
            odd = odd.replace('.', '_')
            shutil.copy('./imgs/captura_janela.png', f'./entradas/{datetime.now().strftime(f"{tipo}_{odd}_%H%M%S.png")}')

        # cancela entradas propostas antes
        if tipo == "back":
            pyautogui.press("c")
        if tipo == "lay":
            pyautogui.press("z")
        time.sleep(5)


    def click_cashout(self):
        try:
            cashout = pyautogui.locateOnScreen("./imgs/cashout.jpg", confidence=0.8)
            pyautogui.click(cashout)  # evitar clicks fora da área certa
            time.sleep(1)
            pyautogui.press("c")
            pyautogui.press("z") # removo apostas propostas
            print('CASHOUT...')
        except:
            print('Não foi possível fazer o CASHOUT')


    def migalha(self) -> str:
        """
        Estratégia que faz lay over limit

        Requisitos:

            odd menor q 1.20

        Returns:

            str: status do processo
        """
        mercado = self.ladder['info']['mercado']
        if "Mais de" not in mercado:
            return (f"Estratégia não pode ser feita no mercado: {mercado}")

        range_odd = float(self.odds_back[0])
        range_odd = range_odd <= 1.2
        if range_odd is False:
            self.click_cashout()
            return f"Range de odd fora: {self.odds_back[0]} e {self.odds_lay[0]}"

        if self.gap > 1:
            return f"GAP maior q o esperado: {self.gap}"

        # peso do dinheiro por odd
        peso_dinheiro_back = [self.ladder['odd'][odd]["back"] for odd in self.odds_back]
        peso_dinheiro_lay = [self.ladder['odd'][odd]["lay"] for odd in self.odds_lay]
        media_dinheiro_back = sum(peso_dinheiro_back) / len(peso_dinheiro_back) - 1
        media_dinheiro_lay = sum(peso_dinheiro_lay) / len(peso_dinheiro_lay) - 1

        # media dinheiro em lay tem q ser maior q 80% da media em back e meu lay tem q ser numa odd com seguranca, ou seja tem pelo menos metade da media do dinheiro em back
        if media_dinheiro_lay > media_dinheiro_back * 0.75:
            if self.gap == 0:  # se tiver sem gap checar melhor odd
                media_em_lay_maior = peso_dinheiro_back[1] < media_dinheiro_back * 0.80
                odd_segura = peso_dinheiro_lay[1] > media_dinheiro_back * 0.50
                if media_em_lay_maior and odd_segura:
                    # atendeu os requisitos comentados, então propoe na odd limite
                    entrada = 1
                else:
                    entrada = 2  # qual odd deixa nossa entrada + segura
                log_msg = f"Migalha sem GAP({entrada}) - Propondo LAY a @{self.odds_lay[entrada]}"
                odd_migalha = self.odds_lay[entrada]

            elif self.gap == 1:  # se tiver gap de 1 tick proponho
                log_msg = f"Migalha com GAP - Propondo LAY a @{self.odds_lay[2]} "
                odd_migalha = self.odds_lay[2]

            else:
                return "ERRO!! Trava GAP"

            # saber se já está proposto...
            if (
                self.ladder['odd'][odd_migalha]["back"] > 0
                and self.ladder['odd'][odd_migalha]["lay"] > 0
            ):
                log_msg = f"Já está proposto no migalha a {odd_migalha}"
                return log_msg

            print(log_msg)
            logging.info(log_msg)
            return odd_migalha

        return "media dinheiro em back é maior q em lay"


    def scalping_under_acima_2_20(self) -> str:
        """
        Estratégia que fará o scalping no under em back

        Requisitos:

            odd entre 6 e 2.20

        Returns:

            str: status do processo
        """
        mercado = self.ladder['info']['mercado']
        if "Menos de" not in mercado:
            return (f"Estratégia não pode ser feita no mercado: {mercado}")

        range_odd = float(self.odds_back[0])
        range_odd = range_odd >= 2.2 and range_odd < 6
        if range_odd is False:
            self.click_cashout()
            return f"Range de odd fora do Scalping Under Limit: {self.odds_back[0]} e {self.odds_lay[0]}"

        if self.gap > 3:
            return f"GAP maior q o esperado: {self.gap}"

        # peso do dinheiro por odd
        peso_dinheiro_back = [self.ladder['odd'][odd]["back"] for odd in self.odds_back]
        peso_dinheiro_lay = [self.ladder['odd'][odd]["lay"] for odd in self.odds_lay]
        media_dinheiro_back = sum(peso_dinheiro_back) / len(peso_dinheiro_back) - 1
        media_dinheiro_lay = sum(peso_dinheiro_lay) / len(peso_dinheiro_lay) - 1

        # analisar o peso do dinheiro do lay para já propor preço no back
        if media_dinheiro_back < media_dinheiro_lay or media_dinheiro_lay > 15000:
            return "Mercado em lay apresenta resistência!"

        # 1° CENÁRIO: primeira odd do lay tem dinheiro e é menor q a média do dinheiro em lay(das 3 odds) dividido por 2 ?
        if peso_dinheiro_lay[1] > 0 and peso_dinheiro_lay[1] < media_dinheiro_lay / 2:
            # Então proponha um back seguro (corresponde a pelo menos 15% da média do dinheiro em back)
            for i in range(len(peso_dinheiro_back)):
                if peso_dinheiro_back[i] > media_dinheiro_back * 0.15:
                    log_msg = f"Scalping 2.2 (1) Propondo preço a ODD de @{self.odds_back[i]}"
                    print(log_msg)
                    logging.info(log_msg)
                    return self.odds_back[i]

        # 2° CENÁRIO: primeira odd do lay vazia E media do dinheiro em back pelo menos 3 vezes maior q lay E as duas últimas odds do back são maiores q 0 ?
        if (
            peso_dinheiro_lay[1] == 0
            and media_dinheiro_back > media_dinheiro_lay * 5
            and peso_dinheiro_back[-1] > 0
            and peso_dinheiro_back[-2] > 0
        ):
            # então proponho em uma odd sem peso de dinheiro
            log_msg = (
                f"Scalping 2.2 (2) Propondo preço a ODD de @{self.odds_back[-3]}"
            )
            print(log_msg)
            logging.info(log_msg)
            return self.odds_back[-3]

        return "Não encontrou odd para propor"

w = Wagertool()
print('START!!')

while True:
    time.sleep(1)
    w.atualizar_qt_janelas()
    for janela in w.janelas:
        print(f'{datetime.now().strftime("%H:%M")} - {janela}')
        # import sys
        # sys.exit() # debug

        if w.captura_janela(janela) == True:
            try:
                w.extrai_valores()
            except:
                print('ERRO ao extrair valores... salvando imagem para debug')
                shutil.copy('./imgs/captura_janela.png', f'./debug_screen/{datetime.now().strftime("extrai_valores_erro_%d%m_%H%M%S.png")}')
                continue

            if w.ladder['info']['status'] != 'AO VIVO':
                if w.ladder['info']['status'] == 'FECHADO':
                    w.janelas.remove(janela) # remove do processo
                    print(f'Mercado encerrado! ladder fechada!')
                    wtool = gw.getWindowsWithTitle(janela)[0]
                    wtool.close()
                print(w.ladder['info']['status'])
                continue

            try:
                w.atualiza_informacoes_da_ladder()
            except TypeError:
                print("Não foi possível atualizar a ladder...")
                continue
            
            if w.ladder['odd'] == {}:
                print('Mercado sem dinheiro na ladder...')
                continue
            # direcionar mercado para uma estratégia apenas
            media_odds_ladder = (
                float(list(w.ladder['odd'])[0]) + float(list(w.ladder['odd'])[-1])
            ) / 2

            if media_odds_ladder <= 1.35:  # migalha
                print("Estratégia selecionada: Migalinha")
                odd = w.migalha()
                print(odd)
                # if odd == 'media dinheiro em back é maior q em lay':
                #     shutil.copy('./imgs/captura_janela.png', f'./debug_screen/{datetime.now().strftime("migalha_%d%m_%H%M%S.png")}')
                if odd in w.ladder['odd'].keys():
                    w.entrada(odd=odd, tipo="lay")

            elif media_odds_ladder > 1.80 and media_odds_ladder <= 7:  # migalha
                print("Estratégia selecionada: Scalping Under")
                odd = w.scalping_under_acima_2_20()
                print(odd)
                if odd in w.ladder['odd'].keys():
                    w.entrada(odd=odd, tipo="back")
            
            else:
                print('Sem estratégia para este evento')


