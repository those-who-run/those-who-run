"""The pit wall: the session store, read-only, in a browser.

``data`` reads the store and returns plain data, as the models in
``api_models``. ``server`` is the data API the React pit wall reads
(``those-who-run pitwall``, #236). ``app`` is the Streamlit page
(``those-who-run web``) and the only module that imports Streamlit, which is an
optional extra (``pip install those-who-run[web]``).
"""
