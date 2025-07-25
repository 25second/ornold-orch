from bs4 import BeautifulSoup, NavigableString, Comment

def mark_interactive_elements(html_content: str) -> str:
    """
    Анализирует HTML, находит все интерактивные элементы и помечает их
    стабильным атрибутом 'data-ornold-id' на основе их содержания.

    Возвращает "очищенный" и размеченный HTML в виде строки.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Удаляем ненужные теги
    for tag in soup.find_all(['script', 'style', 'svg', 'path']):
        tag.decompose()

    # 2. Очищаем текст от лишних пробелов
    for element in soup.find_all(string=True):
        if isinstance(element, (NavigableString, Comment)):
            continue
        cleaned_text = ' '.join(element.strip().split())
        element.replace_with(cleaned_text)

    # 3. Находим и помечаем интерактивные элементы стабильными ID
    interactive_tags = ['a', 'button', 'input', 'textarea', 'select', '[role="button"]', '[role="link"]']
    
    used_ids = set()
    counter = 0

    for selector in interactive_tags:
        for element in soup.select(selector):
            if 'style' in element.attrs and 'display: none' in element['style']:
                continue
            
            # Генерируем ID на основе типа тега и текста/атрибутов
            tag_name = element.name
            text_content = element.get_text(strip=True)[:30] # Первые 30 символов текста
            placeholder = element.get('placeholder', '')[:30]
            aria_label = element.get('aria-label', '')[:30]

            base_id_str = f"{tag_name}_{text_content}_{placeholder}_{aria_label}"
            
            # Делаем ID уникальным, если такой уже есть
            final_id = base_id_str
            c = 1
            while final_id in used_ids:
                final_id = f"{base_id_str}_{c}"
                c += 1
            
            used_ids.add(final_id)
            element['data-ornold-id'] = final_id
            
    body_content = soup.find('body')
    return str(body_content) if body_content else ""

if __name__ == '__main__':
    # Пример использования для отладки
    test_html = """
    <html>
    <head>
        <title>Test Page</title>
        <style>.hidden { display: none; }</style>
    </head>
    <body>
        <h1>Welcome</h1>
        <p>Some text here.   And more     text.
        </p>
        <a href="/login">Click to Login</a>
        <button type="submit">Submit Form</button>
        <input type="text" placeholder="Username">
        <input type="password" class="hidden">
        <div role="button" tabindex="0">Custom Button</div>
        <script>alert('hello');</script>
    </body>
    </html>
    """
    marked_html = mark_interactive_elements(test_html)
    print(marked_html)
    
    # Ожидаемый результат (примерный):
    # <body data-ornold-id-body="1"><h1>Welcome</h1><p>Some text here. And more text.</p><a data-ornold-id="1" href="/login">Click to Login</a><button data-ornold-id="2" type="submit">Submit Form</button><input data-ornold-id="3" placeholder="Username" type="text"/><div data-ornold-id="4" role="button" tabindex="0">Custom Button</div></body> 