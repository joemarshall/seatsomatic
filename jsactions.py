class JSAction:

    def __init__(self,jscode):
        self.jscode=rf"""
        (function(){{
                {jscode}
        }})().then(window.pywebview.api.action_success).catch(window.pywebview.api.action_fail);"""


    def apply(self,window,callback,exceptionCallback):
#        print(f"Applying JSAction {self} with code: \n")
#        print(self.jscode)
        try:
            window.run_js(self.jscode)
#            print("JSAction applied successfully:")
        except Exception as e:
            print(f"Error applying JSAction {self}: {e}")
            exceptionCallback(str(e))


class JSWait(JSAction):
    def __init__(self,*,timeout):
        super().__init__(f"return new Promise(resolve => setTimeout(resolve, {timeout},true));")



class JSDoSomethingWithTimeout(JSAction):
    def __init__(self,js_todo,*,timeout):
##        print("Timeout:",timeout)
        super().__init__(r"""
            function doIt(){
try {
                """+js_todo+"""
} catch (error) {
  console.error(error);
  return false;
  }

            }
            const python_timeout="""+str(timeout)+""";

        async function doWithTimeout(timeout)
        {
            var elapsed=0;
            while(python_timeout==0 || elapsed<python_timeout){
                if(doIt()){
                    return true;
                }
                if(timeout<=0){
                    await new Promise(resolve => setTimeout(resolve, 2000));
                }else{
                    await new Promise(resolve => setTimeout(resolve, 200));
                    console.log("Elapsed time:",elapsed,"ms");
                    elapsed+=200;
                }
            }
            return false;
        }
        return doWithTimeout(python_timeout);
        """)

class JSActionBringToFront(JSDoSomethingWithTimeout):
    def __init__(self):
        super().__init__("return true",timeout=1000)

    def apply(self,window,callback,exceptionCallback):
        window.on_top = True
        print(f"Bringing window to front for JSAction {self}")
        super().apply(window,callback,exceptionCallback)


class JSDoLoginPages(JSDoSomethingWithTimeout):
    def __init__(self):
        super().__init__("""            
            var signinOptions=document.querySelector('[data-test-id="signinOptions"]');
            if(signinOptions){
                console.log("Found signin options, clicking ");
                signinOptions.click();
                return false;
            }

            if()
            return false;
        """,timeout=5000)

class JSFailIfLoggedIn(JSDoSomethingWithTimeout):
    def __init__(self,base_url,target_url):
        super().__init__(f"""
            let base_url = "{base_url}";
            let target_url = "{target_url}";
            if(window.location.href.startsWith(base_url)){{
                return false;
            }}""",timeout=500)

class JSNavigateToMainPage(JSDoSomethingWithTimeout):
    def __init__(self,base_url,target_url):
        super().__init__(f"""
            let base_url = "{base_url}";
            let target_url = "{target_url}";
            """ """
            if(window.location.href.startsWith(base_url))
             {
                if(document.title.toLowerCase().includes('lectures')){
                        console.log("Already on lectures page,",document.title);
                        return true;
                }else{
                    console.log("Navigating to lectures page");
                    document.location.href=target_url;
                    return false;
                }
            }else{
                console.log("Waiting for lectures page");
                return false;
            }
                            """,timeout=5000)


class JSDoSomethingToElementsWithTimeout(JSDoSomethingWithTimeout):
    def __init__(self,js_element_fn,element_selector,*,timeout=2000):
        element_selector_escaped=element_selector.replace("'","\\'")
        super().__init__(f"""
            function doToElement(element){{
                {js_element_fn}
            }}
            let retval = false;
            for(let element of document.querySelectorAll('{element_selector_escaped}')){{
                if(doToElement(element)){{
                    retval = true;
                }}
            }}
            return retval;
        """,timeout=timeout)


class JSClickByText(JSDoSomethingToElementsWithTimeout):
    def __init__(self,text,*,element_type="div",timeout=2000):
        super().__init__(f"""
            let search_text= '{text}';""" +"""
            let tc = element.textContent?element.textContent.trim().toLowerCase():"";
            if(!tc){
                tc=element.value?element.value.trim().toLowerCase():"";
            }
            if (tc === search_text.toLowerCase()) {
                console.log('Found text to click:', search_text, '=>', element.textContent.trim());
                element.click();
                return true;
            }else{
                return false;
            }""",element_selector=element_type,timeout=timeout)
        
class JSClickByMultiText(JSDoSomethingToElementsWithTimeout):
    def __init__(self,texts,click_selector,*,element_type="div",timeout=2000):
        click_selector=click_selector.replace("'","\\'")
        super().__init__(f"""
            let search_texts= {texts};
            let click_selector='{click_selector}'; """+
            """
            console.log("Checking element:"+element);

            let tc = element.textContent?element.textContent.trim().toLowerCase():"";
            console.log("Checking element:"+tc);
            for (let t of search_texts)
            {
                if(!tc.includes(t.toLowerCase().trim()))
                {
                    console.log('Text not found in element, skipping:', t, '=>', tc);
                    return false;

                }
            }

            console.log('Found multitext:', element.textContent.trim());
            element.querySelector(click_selector).click();
            return true;
            """,element_selector=element_type,timeout=timeout)
        
        

class JSInputBySelector(JSDoSomethingToElementsWithTimeout):
    def __init__(self,selector,value,timeout=2000):
        super().__init__(f"""
            let value='{value}';"""+

            """
            element.focus()
            element.value=""
            element.value = value;
            element.dispatchEvent(new InputEvent('input', { data: value, bubbles: true }))
            return true;
        """,element_selector=selector,timeout=timeout)
        
class JSClickBySelector(JSDoSomethingToElementsWithTimeout):
    def __init__(self,selector,timeout=2000):
        super().__init__("element.click();return true;",element_selector=selector,timeout=timeout)


class JSHoldWhileVisibleXPath(JSDoSomethingWithTimeout):
    def __init__(self,selector,timeout=0):
        selector_escaped=selector.replace("'","\\'")
        super().__init__(f"""
            let selector='{selector_escaped}';
            """+ """            
            let element=document.evaluate(selector, document,null,2).stringValue;
            if(element){
                console.log("Element still visible, waiting:",selector);
                return false;
            }else{
                console.log("Element not visible, restarting:",selector);
                return true;
            }
        """,timeout=0)

class JSHoldWhileVisible(JSDoSomethingWithTimeout):
    def __init__(self,selector,timeout=0):
        selector_escaped=selector.replace("'","\\'")
        super().__init__(f"""
            let selector='{selector_escaped}';
            """ + """
            let element=document.querySelector(selector);
            if(element){
                console.log("Element still visible, waiting:",selector);
                return false;
            }else{
                console.log("Element not visible, restarting:",selector);
                return true;
            }
        """,timeout=timeout)
