<?php
function axiom_valuation_api_url(){return apply_filters('axiom_valuation_api_url','http://127.0.0.1:8765/v1/valuations/legacy');}
function axiom_enqueue_valuation_client(){wp_enqueue_script('axiom-valuation-client',plugins_url('../axiom-valuation-client.js',__FILE__),array(),'1.0.0',true);wp_add_inline_script('axiom-valuation-client','window.AXIOM_VALUATION_API='.wp_json_encode(axiom_valuation_api_url()).';','before');}
add_action('wp_enqueue_scripts','axiom_enqueue_valuation_client');
