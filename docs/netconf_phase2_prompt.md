# **Antigravity Task Brief: NETCONF Phase 2 \- \<edit-config\>**

## **1\. Project Context & Recent Architectural Fixes**

You are acting as a **Senior Network Automation Software Architect** working on the gnmi\_client\_py repository.

**Recent System Update (Crucial Context):**

We recently identified and fixed a critical state-management bug. Previously, all workers shared a single, global ParsedConfig data class, which caused major routing and state conflicts during multi-target/multi-protocol executions.

**The Fix:** We have successfully decoupled this. The system now utilizes polymorphic, independent session configurations (GNMISessionConfig and NetconfSessionConfig). Each worker thread now operates on its own isolated session state. **You must respect this boundary and never revert to global config assumptions.**

## **2\. Active Objective: Phase 2 Payload Generation**

We have successfully implemented Phase 1 (read-only NETCONF RPCs: \<get\>, \<get-config\>, and RFC 6022 \<get-schema\>).

Our immediate goal is **Phase 2: Implementing the \<edit-config\> operation** by mapping our universal SetWorker payloads into valid NETCONF operations using ncclient.

## **3\. Step-by-Step Implementation Directives**

Please execute the following roadmap in order. Provide your planned diffs for review before applying them.

### **Step 1: Implement NetconfClient.set()**

**Objective:** Complete the set method in specs/client.py to handle configuration modifications.

**Tasks:**

1. Implement the signature: set(self, updates: list \= None, replaces: list \= None, deletes: list \= None, \*\*kwargs) \-\> Any.  
2. **Target Resolution:** Extract the target datastore using kwargs.get('target', 'running') (allowing candidate or running).  
3. **Payload Assembly & Operation Mapping:**  
   * If kwargs.get('config') is provided (a raw XML string or file path), pass it directly as the payload.  
   * Map updates \-\> \<edit-config default-operation="merge"\>.  
   * Map replaces \-\> \<edit-config default-operation="replace"\>.  
   * Map deletes \-\> \<edit-config default-operation="delete"\> (or remove).  
     *(Note: Since we are in the "lite" NETCONF phase, you can assume updates/replaces will either be raw XML snippet strings or we will rely on ncclient's dict-to-XML features if the user passes a dictionary).*  
4. Call self.session.edit\_config(target=..., config=...).  
5. Ensure RPCError exceptions are caught and returned just like in get(), so the NETCONFFormatter can parse them.

### **Step 2: Bind the Worker and Manager**

**Objective:** Ensure the generic SetWorker and ManagerFactory cleanly route to the new client functionality.

**Tasks:**

1. Verify managers/unary\_worker.py: Ensure SetWorker securely passes its updates, replaces, deletes, and all extra \*\*kwargs directly to client.set(\*\*self.kwargs).  
2. Verify managers/factory.py: Ensure the factory safely generates a NetconfClient when protocol \== 'netconf'.

### **Step 3: CLI & Configuration Mapping**

**Objective:** Ensure ui/cmd.py correctly parses \<edit-config\> arguments.

**Tasks:**

1. In the netconf subparser, ensure the edit-config operation is mapped.  
2. Ensure arguments for \--target (default: running), \--default-operation, and \--config (path or string) are captured and packaged safely into the NetconfSessionConfig.

## **4\. Execution Constraints & Guardrails**

* **Protocol Strictness:** ncclient MUST NOT be imported anywhere outside of specs/client.py.  
* **Worker Purity:** Workers (SetWorker) must remain completely protocol-agnostic. They only pass kwargs.  
* **Review Gate:** Present a unified diff of specs/client.py and wait for approval before editing ui/cmd.py or any worker files.