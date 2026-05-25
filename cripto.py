import requests
from colorama import Fore, Style
from typing import Dict, List, Optional, Tuple
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


class Coin:
    """Класс для представления криптовалюты и её цен на разных биржах."""
    
    def __init__(self, name: str, ticker: str, exchange_fees: Optional[Dict[str, tuple]] = None):
        """
        Конструктор класса Coin.
        
        :param name: Название криптовалюты (например, "Bitcoin")
        :param ticker: Тикер (например, "BTC")
        :param exchange_fees: Словарь комиссий бирж (maker_buy, maker_sell, withdrawal_fee)
        """
        self.name = name
        self.ticker = ticker
        self.markets_bid: Dict[str, float] = {}  # Bid цены (цена продажи для maker)
        self.markets_ask: Dict[str, float] = {}  # Ask цены (цена покупки для maker)
        self.market_cap: Optional[float] = None  # Капитализация в USD
        self.exchange_fees = exchange_fees or {}

    def calculate_net_profit(self, buy_market: str, sell_market: str) -> float:
        """
        Вычисляет чистую прибыль с учетом всех комиссий (покупка maker по ask, вывод, продажа maker по bid).
        
        :param buy_market: Биржа для покупки
        :param sell_market: Биржа для продажи
        :return: Чистая прибыль в процентах
        """
        if buy_market not in self.markets_ask or sell_market not in self.markets_bid:
            return 0.0
        
        # Покупаем по ask цене (maker buy = ask)
        buy_price = self.markets_ask[buy_market]
        # Продаем по bid цене (maker sell = bid)
        sell_price = self.markets_bid[sell_market]
        
        if buy_price <= 0 or sell_price <= 0:
            return 0.0
        
        # Получаем комиссии (по умолчанию консервативные значения)
        buy_fees = self.exchange_fees.get(buy_market, (0.002, 0.002, 0.001))
        sell_fees = self.exchange_fees.get(sell_market, (0.002, 0.002, 0.001))
        
        maker_fee_buy = buy_fees[0]      # Комиссия за покупку (maker)
        withdrawal_fee = buy_fees[2]     # Комиссия за вывод (процент от суммы)
        maker_fee_sell = sell_fees[1]    # Комиссия за продажу (maker)
        
        # Эффективная цена покупки: ask цена * (1 + комиссия покупки) * (1 + комиссия вывода)
        effective_buy_price = buy_price * (1 + maker_fee_buy) * (1 + withdrawal_fee)
        
        # Эффективная цена продажи: bid цена * (1 - комиссия продажи)
        effective_sell_price = sell_price * (1 - maker_fee_sell)
        
        if effective_buy_price <= 0:
            return 0.0
        
        # Чистая прибыль в процентах
        net_profit = (effective_sell_price / effective_buy_price - 1) * 100
        return net_profit

    def get_best_arbitrage_pair(self) -> Optional[Tuple[str, str, float]]:
        """Возвращает лучшую пару (биржа покупки, биржа продажи, чистая прибыль %) или None."""
        valid_markets = [m for m in set(list(self.markets_bid.keys()) + list(self.markets_ask.keys()))
                         if self.markets_bid.get(m, 0) > 0 and self.markets_ask.get(m, 0) > 0]
        if len(valid_markets) < 2:
            return None
        best = None
        best_profit = -999.0
        for buy_m in valid_markets:
            for sell_m in valid_markets:
                if buy_m == sell_m:
                    continue
                p = self.calculate_net_profit(buy_m, sell_m)
                if p > best_profit:
                    best_profit = p
                    best = (buy_m, sell_m, p)
        return best

    def get_execution_plan(self, buy_market: str, sell_market: str, amount_usdt: float) -> Optional[Dict]:
        """
        План исполнения арбитража с учётом всех комиссий и переводов.
        :param amount_usdt: Сумма в USDT на покупку на бирже покупки
        :return: Словарь с полями: buy_price, buy_fee_pct, buy_fee_usdt, amount_coin, withdrawal_fee_pct,
                 withdrawal_fee_usdt, sell_price, sell_fee_pct, sell_fee_usdt, revenue_usdt, net_profit_usdt, net_profit_pct
        """
        if buy_market not in self.markets_ask or sell_market not in self.markets_bid:
            return None
        buy_price = self.markets_ask[buy_market]
        sell_price = self.markets_bid[sell_market]
        if buy_price <= 0 or sell_price <= 0:
            return None
        buy_fees = self.exchange_fees.get(buy_market, (0.002, 0.002, 0.001))
        sell_fees = self.exchange_fees.get(sell_market, (0.002, 0.002, 0.001))
        maker_fee_buy, _, withdrawal_fee_pct = buy_fees[0], buy_fees[1], buy_fees[2]
        _, maker_fee_sell, _ = sell_fees[0], sell_fees[1], sell_fees[2]

        # Покупка: комиссия биржи (maker) с суммы в USDT
        buy_fee_usdt = amount_usdt * maker_fee_buy
        amount_after_buy_fee = amount_usdt - buy_fee_usdt
        amount_coin = amount_after_buy_fee / buy_price  # количество монеты

        # Комиссия вывода: % от суммы перевода (в USDT-эквиваленте)
        withdrawal_fee_usdt = amount_after_buy_fee * withdrawal_fee_pct
        value_after_withdrawal = amount_after_buy_fee - withdrawal_fee_usdt
        amount_coin_after_withdrawal = value_after_withdrawal / buy_price

        # Продажа на второй бирже
        revenue_before_sell_fee = amount_coin_after_withdrawal * sell_price
        sell_fee_usdt = revenue_before_sell_fee * maker_fee_sell
        revenue_usdt = revenue_before_sell_fee - sell_fee_usdt

        net_profit_usdt = revenue_usdt - amount_usdt
        net_profit_pct = (net_profit_usdt / amount_usdt) * 100 if amount_usdt else 0

        return {
            "buy_market": buy_market,
            "sell_market": sell_market,
            "amount_usdt": amount_usdt,
            "buy_price": buy_price,
            "buy_fee_pct": maker_fee_buy * 100,
            "buy_fee_usdt": buy_fee_usdt,
            "amount_coin": amount_coin,
            "withdrawal_fee_pct": withdrawal_fee_pct * 100,
            "withdrawal_fee_usdt": withdrawal_fee_usdt,
            "amount_coin_after_withdrawal": amount_coin_after_withdrawal,
            "sell_price": sell_price,
            "sell_fee_pct": maker_fee_sell * 100,
            "sell_fee_usdt": sell_fee_usdt,
            "revenue_usdt": revenue_usdt,
            "net_profit_usdt": net_profit_usdt,
            "net_profit_pct": net_profit_pct,
        }

    @property
    def markets(self) -> Dict[str, float]:
        """Возвращает словарь со средними ценами (для обратной совместимости)."""
        result = {}
        for market in set(list(self.markets_bid.keys()) + list(self.markets_ask.keys())):
            bid = self.markets_bid.get(market, 0)
            ask = self.markets_ask.get(market, 0)
            if bid > 0 and ask > 0:
                result[market] = (bid + ask) / 2
            elif bid > 0:
                result[market] = bid
            elif ask > 0:
                result[market] = ask
        return result

    @property
    def percentage_difference(self) -> float:
        """Вычисляет процентную разницу между максимальной и минимальной ценой (без учета комиссий)."""
        markets_dict = self.markets
        if not markets_dict or len(markets_dict) < 2:
            return 0.0
        
        valid_prices = [price for price in markets_dict.values() if price > 0]
        if len(valid_prices) < 2:
            return 0.0
        
        max_value = max(valid_prices)
        min_value = min(valid_prices)
        
        if min_value == 0:
            return 0.0
        return (max_value / min_value - 1) * 100

    @property
    def net_percentage_difference(self) -> float:
        """Вычисляет максимальную чистую прибыль с учетом всех комиссий."""
        valid_markets = set(list(self.markets_bid.keys()) + list(self.markets_ask.keys()))
        valid_markets = [m for m in valid_markets 
                        if self.markets_bid.get(m, 0) > 0 and self.markets_ask.get(m, 0) > 0]
        
        if len(valid_markets) < 2:
            return 0.0
        
        max_net_profit = 0.0
        for buy_market in valid_markets:
            for sell_market in valid_markets:
                if buy_market != sell_market:
                    profit = self.calculate_net_profit(buy_market, sell_market)
                    max_net_profit = max(max_net_profit, profit)
        
        return max_net_profit

    def get_table_view(self, market: str, col_width: int) -> str:
        """Возвращает отформатированную среднюю цену (bid+ask)/2 с цветовой индикацией."""
        markets_dict = self.markets
        if market not in markets_dict or markets_dict[market] == 0:
            return f"{0:<{col_width}}"
        
        price = markets_dict[market]
        price_str = f"{price:<{col_width}.8f}".rstrip('0').rstrip('.')
        
        valid_prices = [p for p in markets_dict.values() if p > 0]
        if len(valid_prices) < 2:
            return price_str
        
        price_max = max(valid_prices)
        price_min = min(valid_prices)
        
        if price == price_max and price_max != price_min:
            return Fore.RED + price_str + Style.RESET_ALL
        if price == price_min and price_max != price_min:
            return Fore.GREEN + price_str + Style.RESET_ALL
        return price_str
    
    def __str__(self) -> str:
        """Возвращает строковое представление криптовалюты."""
        return f"{self.name} ({self.ticker})"


class ExchangeAPI:
    """Базовый класс для работы с API бирж."""
    
    TIMEOUT = 10  # Таймаут для запросов в секундах
    
    @staticmethod
    def fetch_data(url: str, timeout: int = TIMEOUT, silent: bool = False) -> Optional[dict]:
        """
        Выполняет HTTP-запрос с обработкой ошибок.
        
        :param url: URL для запроса
        :param timeout: Таймаут в секундах
        :param silent: Если True, не выводит сообщения об ошибках
        """
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            if not silent:
                print(f"{Fore.YELLOW}Таймаут при запросе{Style.RESET_ALL}")
            return None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Too Many Requests
                if not silent:
                    print(f"{Fore.YELLOW}Лимит запросов достигнут (429). Продолжаем с имеющимися данными...{Style.RESET_ALL}")
                return None
            if not silent:
                print(f"{Fore.RED}HTTP ошибка {e.response.status_code}: {e}{Style.RESET_ALL}")
            return None
        except requests.exceptions.RequestException as e:
            if not silent:
                print(f"{Fore.RED}Ошибка при запросе: {e}{Style.RESET_ALL}")
            return None
        except Exception as e:
            if not silent:
                print(f"{Fore.RED}Неожиданная ошибка: {e}{Style.RESET_ALL}")
            return None


class ArbitrageFinder:
    """Класс для поиска арбитражных возможностей."""
    
    def __init__(self):
        self.coins: Dict[str, Coin] = {}
        self.markets: List[str] = []
        self.col_width = {"Ticker": 12, "Price": 15, "Difference": 12}
        
        # Комиссии бирж: (maker_fee_buy, maker_fee_sell, withdrawal_fee_percent)
        # withdrawal_fee_percent - процент от суммы вывода (обычно 0-0.1%)
        self.exchange_fees: Dict[str, tuple] = {
            'binance': (0.001, 0.001, 0.0005),    # 0.1% buy, 0.1% sell, 0.05% withdrawal
            'bybit': (0.001, 0.001, 0.0005),      # 0.1% buy, 0.1% sell, 0.05% withdrawal
            'okx': (0.0008, 0.0008, 0.0005),      # 0.08% buy, 0.08% sell, 0.05% withdrawal
            'kucoin': (0.001, 0.001, 0.0005),     # 0.1% buy, 0.1% sell, 0.05% withdrawal
            'mexc': (0.002, 0.002, 0.0005),       # 0.2% buy, 0.2% sell, 0.05% withdrawal
            'huobi': (0.002, 0.002, 0.0005),      # 0.2% buy, 0.2% sell, 0.05% withdrawal
            'upbit': (0.0005, 0.0005, 0.0005),    # 0.05% buy, 0.05% sell, 0.05% withdrawal
        }
    
    def add_binance(self) -> bool:
        """Добавляет данные с Binance (bid/ask цены)."""
        url = "https://api.binance.com/api/v3/ticker/bookTicker"
        data = ExchangeAPI.fetch_data(url)
        if not data:
            return False
        
        self.markets.append('binance')
        usdt_pairs = [item for item in data if item.get('symbol', '').endswith('USDT')]
        
        for pair in usdt_pairs:
            symbol = pair['symbol'][:-4]  # Убираем 'USDT'
            if symbol not in self.coins:
                self.coins[symbol] = Coin('', symbol, self.exchange_fees)
            try:
                bid_price = float(pair.get('bidPrice', 0) or 0)
                ask_price = float(pair.get('askPrice', 0) or 0)
                if bid_price > 0 and ask_price > 0:
                    self.coins[symbol].markets_bid['binance'] = bid_price
                    self.coins[symbol].markets_ask['binance'] = ask_price
            except (ValueError, TypeError):
                continue
        return True

    def add_upbit(self) -> bool:
        """Добавляет данные с Upbit."""
        markets_url = "https://api.upbit.com/v1/market/all"
        markets_data = ExchangeAPI.fetch_data(markets_url)
        if not markets_data:
            return False
        
        usdt_pairs = [m["market"] for m in markets_data if m.get("market", "").startswith("USDT-")]
        if not usdt_pairs:
            return False
        
        ticker_url = f"https://api.upbit.com/v1/ticker?markets={','.join(usdt_pairs)}"
        ticker_data = ExchangeAPI.fetch_data(ticker_url)
        if not ticker_data:
            return False
        
        self.markets.append('upbit')
        for coin in ticker_data:
            symbol = coin.get('market', '')[5:]  # Убираем 'USDT-'
            if not symbol:
                continue
            if symbol not in self.coins:
                self.coins[symbol] = Coin('', symbol, self.exchange_fees)
            try:
                bid_price = float(coin.get('highest_bid_price', 0) or 0)
                ask_price = float(coin.get('lowest_ask_price', 0) or 0)
                if bid_price > 0 and ask_price > 0:
                    self.coins[symbol].markets_bid['upbit'] = bid_price
                    self.coins[symbol].markets_ask['upbit'] = ask_price
            except (ValueError, TypeError):
                continue
        return True

    def add_bybit(self) -> bool:
        """Добавляет данные с Bybit."""
        url = "https://api.bybit.com/v5/market/tickers?category=spot"
        data = ExchangeAPI.fetch_data(url)
        if not data or 'result' not in data or 'list' not in data['result']:
            return False
        
        self.markets.append('bybit')
        usdt_pairs = [ticker for ticker in data["result"]["list"] 
                     if ticker.get("symbol", "").endswith("USDT")]
        
        for pair in usdt_pairs:
            symbol = pair.get('symbol', '')[:-4]  # Убираем 'USDT'
            if not symbol:
                continue
            if symbol not in self.coins:
                self.coins[symbol] = Coin('', symbol, self.exchange_fees)
            try:
                bid_price = float(pair.get('bid1Price', 0) or 0)
                ask_price = float(pair.get('ask1Price', 0) or 0)
                if bid_price > 0 and ask_price > 0:
                    self.coins[symbol].markets_bid['bybit'] = bid_price
                    self.coins[symbol].markets_ask['bybit'] = ask_price
            except (ValueError, TypeError):
                continue
        return True

    def add_okx(self) -> bool:
        """Добавляет данные с OKX."""
        url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
        data = ExchangeAPI.fetch_data(url)
        if not data or 'data' not in data:
            return False
        
        self.markets.append('okx')
        usdt_pairs = [ticker for ticker in data['data'] 
                     if ticker.get('instId', '').endswith('-USDT')]
        
        for pair in usdt_pairs:
            symbol = pair.get('instId', '')[:-5]  # Убираем '-USDT'
            if not symbol:
                continue
            if symbol not in self.coins:
                self.coins[symbol] = Coin('', symbol, self.exchange_fees)
            try:
                bid_price = float(pair.get('bidPx', 0) or 0)
                ask_price = float(pair.get('askPx', 0) or 0)
                if bid_price > 0 and ask_price > 0:
                    self.coins[symbol].markets_bid['okx'] = bid_price
                    self.coins[symbol].markets_ask['okx'] = ask_price
            except (ValueError, TypeError):
                continue
        return True

    def add_huobi(self) -> bool:
        """Добавляет данные с Huobi (используем close как приближение для bid/ask)."""
        url = "https://api.huobi.pro/market/tickers"
        data = ExchangeAPI.fetch_data(url)
        if not data or 'data' not in data:
            return False
        
        self.markets.append('huobi')
        usdt_pairs = [ticker for ticker in data.get('data', []) 
                     if ticker.get('symbol', '').lower().endswith('usdt')]
        
        for pair in usdt_pairs:
            symbol = pair.get('symbol', '').upper()[:-4]  # Убираем 'USDT'
            if not symbol:
                continue
            if symbol not in self.coins:
                self.coins[symbol] = Coin('', symbol, self.exchange_fees)
            try:
                # Huobi ticker не содержит bid/ask напрямую, используем close как приближение
                price = float(pair.get('close', 0) or 0)
                if price > 0:
                    # Используем цену с небольшим спредом как bid и ask (приближение)
                    self.coins[symbol].markets_bid['huobi'] = price * 0.9995
                    self.coins[symbol].markets_ask['huobi'] = price * 1.0005
            except (ValueError, TypeError):
                continue
        return True

    def add_kucoin(self) -> bool:
        """Добавляет данные с KuCoin (bid/ask цены)."""
        url = "https://api.kucoin.com/api/v1/market/allTickers"
        data = ExchangeAPI.fetch_data(url)
        if not data or 'data' not in data or 'ticker' not in data['data']:
            return False
        
        self.markets.append('kucoin')
        usdt_pairs = [ticker for ticker in data['data']['ticker'] 
                     if ticker.get('symbol', '').endswith('-USDT')]
        
        for pair in usdt_pairs:
            symbol = pair.get('symbol', '')[:-5]  # Убираем '-USDT'
            if not symbol:
                continue
            if symbol not in self.coins:
                self.coins[symbol] = Coin('', symbol, self.exchange_fees)
            try:
                # KuCoin allTickers не содержит bid/ask, используем bestBid и bestAsk
                bid_price = float(pair.get('bestBid', 0) or 0)
                ask_price = float(pair.get('bestAsk', 0) or 0)
                if bid_price > 0 and ask_price > 0:
                    self.coins[symbol].markets_bid['kucoin'] = bid_price
                    self.coins[symbol].markets_ask['kucoin'] = ask_price
            except (ValueError, TypeError):
                continue
        return True

    def add_mexc(self) -> bool:
        """Добавляет данные с MEXC (bid/ask цены)."""
        url = "https://api.mexc.com/api/v3/ticker/bookTicker"
        data = ExchangeAPI.fetch_data(url)
        if not data:
            return False
        
        self.markets.append('mexc')
        usdt_pairs = [ticker for ticker in data if ticker.get('symbol', '').endswith('USDT')]
        
        for pair in usdt_pairs:
            symbol = pair.get('symbol', '')[:-4]  # Убираем 'USDT'
            if not symbol:
                continue
            if symbol not in self.coins:
                self.coins[symbol] = Coin('', symbol, self.exchange_fees)
            try:
                bid_price = float(pair.get('bidPrice', 0) or 0)
                ask_price = float(pair.get('askPrice', 0) or 0)
                if bid_price > 0 and ask_price > 0:
                    self.coins[symbol].markets_bid['mexc'] = bid_price
                    self.coins[symbol].markets_ask['mexc'] = ask_price
            except (ValueError, TypeError):
                continue
        return True

    def fetch_market_caps(self, min_market_cap: float = 50_000_000) -> None:
        """Загружает данные о капитализации монет через CoinGecko API."""
        print(f"{Fore.CYAN}Загрузка данных о капитализации...{Style.RESET_ALL}")
        
        # Получаем список всех монет с их капитализацией
        # Используем несколько страниц для получения большего количества монет
        market_cap_dict: Dict[str, float] = {}
        
        for page in range(1, 21):  # Получаем до 20 страниц (5000 монет)
            url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}&sparkline=false"
            # Используем silent=True для страниц, чтобы не спамить ошибками
            data = ExchangeAPI.fetch_data(url, silent=(page > 1))
            
            if not data or not isinstance(data, list):
                # Если получили 429 или другую ошибку, продолжаем с имеющимися данными
                break
            
            # Если на странице нет данных, выходим
            if not data:
                break
            
            for coin_data in data:
                symbol = coin_data.get('symbol', '').upper()
                market_cap = coin_data.get('market_cap', 0)
                if symbol and market_cap and market_cap >= min_market_cap:
                    # Сохраняем максимальную капитализацию, если тикер повторяется
                    if symbol not in market_cap_dict or market_cap > market_cap_dict[symbol]:
                        market_cap_dict[symbol] = market_cap
            
            # Если на странице меньше 250 монет, это последняя страница
            if len(data) < 250:
                break
            
            # Небольшая задержка для избежания rate limiting (CoinGecko лимит: ~10-50 запросов/мин)
            if page < 20:  # Не делаем задержку после последнего запроса
                time.sleep(0.6)
        
        # Присваиваем капитализацию монетам
        found_count = 0
        for ticker, coin in self.coins.items():
            if ticker in market_cap_dict:
                coin.market_cap = market_cap_dict[ticker]
                found_count += 1
        
        print(f"{Fore.GREEN}✓{Style.RESET_ALL} Найдено монет с капитализацией >= ${min_market_cap/1_000_000:.0f}M: {found_count}")

    def fetch_all_exchanges(self, exchange_list: Optional[List[str]] = None) -> None:
        """Загружает данные со всех указанных бирж параллельно."""
        exchange_methods = {
            'binance': self.add_binance,
            'upbit': self.add_upbit,
            'bybit': self.add_bybit,
            'okx': self.add_okx,
            'huobi': self.add_huobi,
            'kucoin': self.add_kucoin,
            'mexc': self.add_mexc,
        }
        
        if exchange_list is None:
            exchange_list = list(exchange_methods.keys())
        
        print(f"{Fore.CYAN}Загрузка данных с бирж...{Style.RESET_ALL}")
        with ThreadPoolExecutor(max_workers=len(exchange_list)) as executor:
            futures = {executor.submit(exchange_methods[name]): name 
                      for name in exchange_list if name in exchange_methods}
            
            for future in as_completed(futures):
                exchange_name = futures[future]
                try:
                    success = future.result()
                    status = f"{Fore.GREEN}✓{Style.RESET_ALL}" if success else f"{Fore.RED}✗{Style.RESET_ALL}"
                    print(f"{status} {exchange_name}")
                except Exception as e:
                    print(f"{Fore.RED}✗{Style.RESET_ALL} {exchange_name}: {e}")

    def output(self, min_difference: float = 0.0, max_difference: Optional[float] = None, min_markets: int = 2, min_market_cap: Optional[float] = None) -> None:
        """
        Выводит таблицу с арбитражными возможностями.
        
        :param min_difference: Минимальная процентная разница
        :param max_difference: Максимальная процентная разница (None = без ограничения)
        :param min_markets: Минимальное количество бирж с ценой
        :param min_market_cap: Минимальная капитализация в USD (None = без фильтрации)
        """
        if not self.markets:
            print(f"{Fore.YELLOW}Нет данных с бирж{Style.RESET_ALL}")
            return
        
        # Заголовок таблицы
        header = f"{'Ticker':<{self.col_width['Ticker']}}"
        for market in self.markets:
            header += f"{market:<{self.col_width['Price']}}"
        header += f"{'Net Profit %':<{self.col_width['Difference']}}"
        print(f"\n{Fore.CYAN}{header}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}(С учетом комиссий: покупка maker, продажа maker, вывод){Style.RESET_ALL}")
        print("-" * (self.col_width['Ticker'] + 
                     len(self.markets) * self.col_width['Price'] + 
                     self.col_width['Difference']))
        
        # Фильтруем и сортируем монеты по чистой прибыли
        filtered_coins = []
        for ticker, coin in self.coins.items():
            # Проверяем базовые условия
            if len(coin.markets) < min_markets:
                continue
            # Используем чистую прибыль с учетом комиссий
            net_profit = coin.net_percentage_difference
            if net_profit < min_difference:
                continue
            # Проверяем максимальный спред
            if max_difference is not None and net_profit > max_difference:
                continue
            # Проверяем капитализацию, если указана
            if min_market_cap is not None:
                if coin.market_cap is None or coin.market_cap < min_market_cap:
                    continue
            filtered_coins.append((ticker, coin))
        
        # Сортируем по чистой прибыли
        filtered_coins.sort(key=lambda x: x[1].net_percentage_difference, reverse=True)
        
        if not filtered_coins:
            cap_msg = f" с капитализацией >= ${min_market_cap/1_000_000:.0f}M" if min_market_cap else ""
            print(f"{Fore.YELLOW}Нет арбитражных возможностей{cap_msg}{Style.RESET_ALL}")
            return
        
        # Выводим данные
        for ticker, coin in filtered_coins:
            row = f"{coin.ticker:<{self.col_width['Ticker']}}"
            for market in self.markets:
                row += coin.get_table_view(market, self.col_width['Price'])
            row += f"{coin.net_percentage_difference:.2f}%"
            print(row)

    def realize_opportunities(
        self,
        min_difference: float = 0.0,
        max_difference: Optional[float] = 10.0,
        min_markets: int = 2,
        amount_usdt: float = 100.0,
        min_profit_to_execute: float = 0.0,
    ) -> None:
        """
        Находит арбитражные возможности и выводит план реализации с учётом всех комиссий и переводов.
        При положительной чистой прибыли после всех затрат — выводит пошаговый план исполнения.
        
        :param min_difference: Минимальный спред (чистая прибыль %)
        :param max_difference: Максимальный спред (чистая прибыль %)
        :param min_markets: Минимум бирж с ценой
        :param amount_usdt: Сумма в USDT для расчёта плана
        :param min_profit_to_execute: Минимальная прибыль в % для вывода плана (фильтр)
        """
        if not self.markets:
            print(f"{Fore.YELLOW}Нет данных с бирж{Style.RESET_ALL}")
            return

        # Те же фильтры, что и в output
        filtered = []
        for ticker, coin in self.coins.items():
            if len(coin.markets) < min_markets:
                continue
            net = coin.net_percentage_difference
            if net < min_difference or (max_difference is not None and net > max_difference):
                continue
            pair = coin.get_best_arbitrage_pair()
            if not pair or pair[2] < min_profit_to_execute:
                continue
            filtered.append((ticker, coin))

        filtered.sort(key=lambda x: x[1].net_percentage_difference, reverse=True)

        if not filtered:
            print(f"{Fore.YELLOW}Нет возможностей для реализации в заданном диапазоне спреда.{Style.RESET_ALL}")
            return

        print(f"\n{Fore.CYAN}——— План реализации арбитража (с учётом всех комиссий и переводов) ———{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Сумма расчёта: {amount_usdt} USDT. Реализуются только возможности с положительной чистой прибылью.{Style.RESET_ALL}\n")

        for ticker, coin in filtered:
            pair = coin.get_best_arbitrage_pair()
            if not pair:
                continue
            buy_market, sell_market, net_pct = pair
            plan = coin.get_execution_plan(buy_market, sell_market, amount_usdt)
            if not plan or plan["net_profit_usdt"] <= 0:
                continue

            p = plan
            print(f"{Fore.GREEN}{coin.ticker}{Style.RESET_ALL} | Чистая прибыль: {p['net_profit_pct']:.2f}% ({p['net_profit_usdt']:.2f} USDT)")
            print(f"  1) Покупка на {p['buy_market']}: {p['amount_usdt']:.2f} USDT → {p['amount_coin']:.8f} {coin.ticker} по цене {p['buy_price']:.8f} | комиссия maker: {p['buy_fee_pct']:.2f}% ({p['buy_fee_usdt']:.2f} USDT)")
            print(f"  2) Вывод с {p['buy_market']} на {p['sell_market']}: комиссия вывода: {p['withdrawal_fee_pct']:.2f}% ({p['withdrawal_fee_usdt']:.2f} USDT) → получите ~{p['amount_coin_after_withdrawal']:.8f} {coin.ticker}")
            print(f"  3) Продажа на {p['sell_market']}: {p['amount_coin_after_withdrawal']:.8f} {coin.ticker} по цене {p['sell_price']:.8f} → {p['revenue_usdt']:.2f} USDT | комиссия maker: {p['sell_fee_pct']:.2f}% ({p['sell_fee_usdt']:.2f} USDT)")
            print(f"  Итого: потрачено {p['amount_usdt']:.2f} USDT, получено {p['revenue_usdt']:.2f} USDT, чистая прибыль {p['net_profit_usdt']:.2f} USDT ({p['net_profit_pct']:.2f}%)\n")


def main():
    """Основная функция."""
    finder = ArbitrageFinder()
    
    # Список бирж для анализа (можно изменить)
    exchanges = ['bybit', 'okx', 'kucoin', 'mexc']  # Добавьте нужные биржи
    
    start_time = time.time()
    finder.fetch_all_exchanges(exchanges)
    elapsed_time = time.time() - start_time
    
    print(f"\n{Fore.CYAN}Время загрузки с бирж: {elapsed_time:.2f} сек{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Загружено монет: {len(finder.coins)}{Style.RESET_ALL}")
    
    # Выводим только арбитражные возможности с разницей от 0% до 10%
    finder.output(min_difference=0.0, max_difference=10.0, min_markets=2)

    # План реализации арбитража с учётом всех комиссий и переводов (только положительная чистая прибыль)
    finder.realize_opportunities(
        min_difference=0.0,
        max_difference=10.0,
        min_markets=2,
        amount_usdt=100.0,
        min_profit_to_execute=0.0,
    )


if __name__ == '__main__':
    main()
