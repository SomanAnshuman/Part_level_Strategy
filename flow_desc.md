**Flows to generate Part Level Strategy**  
**v1**  
Feature level Strategies using LLM (prompting features in batches) -> Part level Strategy

**v2**  
Feature level Strategies using LLM (prompting single feature at a time) -> Part level Strategy

**v3**  
Feature level Strategies using LLM (prompting single feature at a time) -> Type level Strategy -> Part level Strategy

**v4**  
Individual Feature level strategies -> Part level strategy  
But the Feature level strategies used will be from KB.

**v5**  
Individual Feature level Strategies from KB -> Refinement at individual level using LLM -> Part level Strategy

**v6**  
Individual Feature level Strategies from KB -> Refinement at individual level using LLM -> Part level Strategy  
Rationale for each strategy using RAG __________________________↑  

**v6_n**  
Individual Feature level Strategies from KB -> Refinement at individual level using LLM -> Part level Strategy  
Rationale for each strategy using RAG by specifying files_________↑   

**v7**  
Individual Feature level Strategies from KB -> Refinement at individual level using LLM -> Part level Strategy  
Spatial Context of part __________________________________________________________________________↑  

**Flows to generate Tools & Params using previously generated Part level Strategy as input**  
_Each tools & params prompt in following flows include: 1. Tool recommendation prompt, 2. Params recommendation prompt_  
**m1**  
Single setup at a time to generate tools & params -> combining new setups in sequence -> Part level Strategy with tools & params

**m2**  
Prompting whole Part level Strategy in one go -> Part level Strategy with tools & params
