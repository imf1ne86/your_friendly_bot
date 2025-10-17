"""
* Класс для использования сервисов ретрокомпьютерных ресурсов
* *************************
* В этом классе используются сервисы ретрокомпьютинга, серверы,
* и сайты, ассоциированные с ретрокомпьютингом (к примеру,
* https://downgrade.hoho.ws).
*
* @author Ефремов А. В., 14.10.2025
"""

import requests

class Downgrade:

    @staticmethod
    def jokes_script(p_lang: str = "", proxy_url: str = "") -> str:
        """
        * Шутка с сервера
        *
        * @param p_lang Двухбуквенный код языка (например, "ru" - русский)
        * @param proxy_url URL proxy-сервера
        * @return Строка с шуткой
        """
        URL: str = "http://downgrade.hoho.ws/jokes/joke.php"
        joke_url: str = URL if "".__eq__(p_lang) else f"{URL}?lang={p_lang.lower()}"
        result: str = ""
        try:
            request_kwargs = {"timeout": 5}
            if proxy_url:
                proxies = {}
                proxies.setdefault("http", proxy_url)
                proxies.setdefault("https", proxy_url)
                request_kwargs["proxies"] = proxies
            r = requests.get(joke_url, **request_kwargs)
            r.raise_for_status()
            m: str = (r.text[len("document.write('"):] if r.text.startswith("document.write('") else r.text)
            m = m[:-3] if m.endswith("');") else m
            # m: str = r.text.removeprefix("document.write('").removesuffix("');")  # Python 3.9+ (короткая альтернатива)
            m = m.replace(f"{chr(92)}", "")
            m = m.replace(f"{chr(10)}", f"{chr(32)}")
            m = m.replace(f"{chr(13)}", "")
            if m is not None:
                result = m
        except Exception:
            pass
        return result
