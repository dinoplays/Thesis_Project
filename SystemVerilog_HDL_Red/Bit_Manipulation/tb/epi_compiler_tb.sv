`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Bit_Manipulation_run_epic_tb.do
*/

module epi_compiler_tb;

	// ------------------------------------------------------------------------
	// Clock: 50 MHz => 20 ns period
	// ------------------------------------------------------------------------
	localparam int TCLK_NS = 20;

	logic clock_50 = 1'b0;
	always #(TCLK_NS/2) clock_50 = ~clock_50;

	// ------------------------------------------------------------------------
	// Parameters
	// ------------------------------------------------------------------------
	parameter int unsigned IMAGE_DIM    = 128;
	parameter int unsigned IMAGE_DIM_BS = 7;
	localparam int unsigned STORAGE_ADDR_W = 2 * IMAGE_DIM_BS;

	localparam int unsigned MID_LOW  = (IMAGE_DIM/2) - 1;
	localparam int unsigned MID_HIGH = (IMAGE_DIM/2);
	localparam int unsigned LAST_IDX = IMAGE_DIM - 1;

	// ------------------------------------------------------------------------
	// Paths
	// ------------------------------------------------------------------------
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/epic/input_data";

	localparam string OUT_DIR_RED   = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/epic/output_data/red";
	localparam string OUT_DIR_GREEN = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/epic/output_data/green";
	localparam string OUT_DIR_BLUE  = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/epic/output_data/blue";

	localparam string IN_SOC_MIF         = {IN_DIR, "/SIM_SOC_IN.mif"};
	localparam string IN_EOC_MIF         = {IN_DIR, "/SIM_EOC_IN.mif"};
	localparam string IN_SOLF_MIF        = {IN_DIR, "/SIM_SOLF_IN.mif"};
	localparam string IN_EOLF_MIF        = {IN_DIR, "/SIM_EOLF_IN.mif"};
	localparam string IN_VALID_MIF       = {IN_DIR, "/SIM_PIXEL_VALID_IN.mif"};
	localparam string IN_PIXEL_RED_MIF   = {IN_DIR, "/SIM_PIXEL_IN_RED.mif"};
	localparam string IN_PIXEL_GREEN_MIF = {IN_DIR, "/SIM_PIXEL_IN_GREEN.mif"};
	localparam string IN_PIXEL_BLUE_MIF  = {IN_DIR, "/SIM_PIXEL_IN_BLUE.mif"};

	// ------------------------------------------------------------------------
	// Depth / sizes
	// ------------------------------------------------------------------------
	localparam int MAX_DEPTH     = 350000;
	localparam int WARMUP_CYCLES = 8;

	localparam int VERTICAL_POST_FRAME_CYCLES = (IMAGE_DIM * IMAGE_DIM);
	localparam int EXTRA_TAIL    = VERTICAL_POST_FRAME_CYCLES;
	localparam int OUT_MAX_DEPTH = 4 + WARMUP_CYCLES + MAX_DEPTH + EXTRA_TAIL + 64;

	int DEPTH = 0;

	// ------------------------------------------------------------------------
	// Input memories
	// ------------------------------------------------------------------------
	logic [14:0] pixel_red_mem   [0:MAX_DEPTH-1];
	logic [14:0] pixel_green_mem [0:MAX_DEPTH-1];
	logic [14:0] pixel_blue_mem  [0:MAX_DEPTH-1];

	logic valid_mem [0:MAX_DEPTH-1];
	logic soc_mem   [0:MAX_DEPTH-1];
	logic eoc_mem   [0:MAX_DEPTH-1];
	logic solf_mem  [0:MAX_DEPTH-1];
	logic eolf_mem  [0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs
	// ------------------------------------------------------------------------
	logic        pixel_valid_in = 1'b0;
	logic        soc_in         = 1'b0;
	logic        eoc_in         = 1'b0;
	logic        solf_in        = 1'b0;
	logic        eolf_in        = 1'b0;

	logic [14:0] pixel_in_red   = 15'd0;
	logic [14:0] pixel_in_green = 15'd0;
	logic [14:0] pixel_in_blue  = 15'd0;

	// ------------------------------------------------------------------------
	// DUT outputs: RED
	// ------------------------------------------------------------------------
	logic                            epi_valid_out_red;
	logic [14:0]                     epi_column_out_red [0:8];
	logic [IMAGE_DIM_BS-1:0]         epi_column_idx_out_red;
	logic [IMAGE_DIM_BS-1:0]         epi_idx_out_red;
	logic                            orientation_out_red;
	logic                            red_shared_banks_5_to_8_released;
	logic                            red_shared_banks_5_to_8_epi_read_active;

	// ------------------------------------------------------------------------
	// DUT outputs: GREEN
	// ------------------------------------------------------------------------
	logic                            epi_valid_out_green;
	logic [14:0]                     epi_column_out_green [0:8];
	logic [IMAGE_DIM_BS-1:0]         epi_column_idx_out_green;
	logic [IMAGE_DIM_BS-1:0]         epi_idx_out_green;
	logic                            orientation_out_green;
	logic                            green_shared_banks_5_to_8_released;
	logic                            green_shared_banks_5_to_8_epi_read_active;

	// ------------------------------------------------------------------------
	// DUT outputs: BLUE
	// ------------------------------------------------------------------------
	logic                            epi_valid_out_blue;
	logic [14:0]                     epi_column_out_blue [0:8];
	logic [IMAGE_DIM_BS-1:0]         epi_column_idx_out_blue;
	logic [IMAGE_DIM_BS-1:0]         epi_idx_out_blue;
	logic                            orientation_out_blue;
	logic                            blue_shared_banks_5_to_8_released;
	logic                            blue_shared_banks_5_to_8_epi_read_active;

	// ------------------------------------------------------------------------
	// Shared storage interface: RED
	// ------------------------------------------------------------------------
	logic                             red_storage_we [0:11];
	logic                             red_storage_we_8v;
	logic [STORAGE_ADDR_W-1:0]        red_storage_wr_addr [0:11];
	logic [STORAGE_ADDR_W-1:0]        red_storage_wr_addr_8v;
	logic [14:0]                      red_storage_wr_data;
	logic [STORAGE_ADDR_W-1:0]        red_storage_rd_addr;
	logic [14:0]                      red_storage_rd_data [0:11];
	logic [14:0]                      red_storage_rd_data_8v;

	logic                             red_fao_we [0:3];
	logic [STORAGE_ADDR_W-1:0]        red_fao_wr_addr [0:3];
	logic [14:0]                      red_fao_wr_data [0:3];
	logic [STORAGE_ADDR_W-1:0]        red_fao_rd_addr [0:3];
	logic [14:0]                      red_fao_rd_data [0:3];

	// ------------------------------------------------------------------------
	// Shared storage interface: GREEN
	// ------------------------------------------------------------------------
	logic                             green_storage_we [0:11];
	logic                             green_storage_we_8v;
	logic [STORAGE_ADDR_W-1:0]        green_storage_wr_addr [0:11];
	logic [STORAGE_ADDR_W-1:0]        green_storage_wr_addr_8v;
	logic [14:0]                      green_storage_wr_data;
	logic [STORAGE_ADDR_W-1:0]        green_storage_rd_addr;
	logic [14:0]                      green_storage_rd_data [0:11];
	logic [14:0]                      green_storage_rd_data_8v;

	logic                             green_fao_we [0:3];
	logic [STORAGE_ADDR_W-1:0]        green_fao_wr_addr [0:3];
	logic [14:0]                      green_fao_wr_data [0:3];
	logic [STORAGE_ADDR_W-1:0]        green_fao_rd_addr [0:3];
	logic [14:0]                      green_fao_rd_data [0:3];

	// ------------------------------------------------------------------------
	// Shared storage interface: BLUE
	// ------------------------------------------------------------------------
	logic                             blue_storage_we [0:11];
	logic                             blue_storage_we_8v;
	logic [STORAGE_ADDR_W-1:0]        blue_storage_wr_addr [0:11];
	logic [STORAGE_ADDR_W-1:0]        blue_storage_wr_addr_8v;
	logic [14:0]                      blue_storage_wr_data;
	logic [STORAGE_ADDR_W-1:0]        blue_storage_rd_addr;
	logic [14:0]                      blue_storage_rd_data [0:11];
	logic [14:0]                      blue_storage_rd_data_8v;

	logic                             blue_fao_we [0:3];
	logic [STORAGE_ADDR_W-1:0]        blue_fao_wr_addr [0:3];
	logic [14:0]                      blue_fao_wr_data [0:3];
	logic [STORAGE_ADDR_W-1:0]        blue_fao_rd_addr [0:3];
	logic [14:0]                      blue_fao_rd_data [0:3];

	// ------------------------------------------------------------------------
	// Instantiate shared storage + DUTs
	// ------------------------------------------------------------------------
	shared_frame_storage #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) RED_STORAGE (
		.clk(clock_50),
		.takeover_banks_5_to_8(red_shared_banks_5_to_8_released),
		.epi_read_banks_5_to_8_active(red_shared_banks_5_to_8_epi_read_active),

		.epi_we(red_storage_we),
		.epi_we_8v(red_storage_we_8v),
		.epi_wr_addr(red_storage_wr_addr),
		.epi_wr_addr_8v(red_storage_wr_addr_8v),
		.epi_wr_data(red_storage_wr_data),
		.epi_rd_addr(red_storage_rd_addr),
		.epi_rd_data(red_storage_rd_data),
		.epi_rd_data_8v(red_storage_rd_data_8v),

		.fao_we(red_fao_we),
		.fao_wr_addr(red_fao_wr_addr),
		.fao_wr_data(red_fao_wr_data),
		.fao_rd_addr(red_fao_rd_addr),
		.fao_rd_data(red_fao_rd_data)
	);

	shared_frame_storage #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) GREEN_STORAGE (
		.clk(clock_50),
		.takeover_banks_5_to_8(green_shared_banks_5_to_8_released),
		.epi_read_banks_5_to_8_active(green_shared_banks_5_to_8_epi_read_active),

		.epi_we(green_storage_we),
		.epi_we_8v(green_storage_we_8v),
		.epi_wr_addr(green_storage_wr_addr),
		.epi_wr_addr_8v(green_storage_wr_addr_8v),
		.epi_wr_data(green_storage_wr_data),
		.epi_rd_addr(green_storage_rd_addr),
		.epi_rd_data(green_storage_rd_data),
		.epi_rd_data_8v(green_storage_rd_data_8v),

		.fao_we(green_fao_we),
		.fao_wr_addr(green_fao_wr_addr),
		.fao_wr_data(green_fao_wr_data),
		.fao_rd_addr(green_fao_rd_addr),
		.fao_rd_data(green_fao_rd_data)
	);

	shared_frame_storage #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) BLUE_STORAGE (
		.clk(clock_50),
		.takeover_banks_5_to_8(blue_shared_banks_5_to_8_released),
		.epi_read_banks_5_to_8_active(blue_shared_banks_5_to_8_epi_read_active),

		.epi_we(blue_storage_we),
		.epi_we_8v(blue_storage_we_8v),
		.epi_wr_addr(blue_storage_wr_addr),
		.epi_wr_addr_8v(blue_storage_wr_addr_8v),
		.epi_wr_data(blue_storage_wr_data),
		.epi_rd_addr(blue_storage_rd_addr),
		.epi_rd_data(blue_storage_rd_data),
		.epi_rd_data_8v(blue_storage_rd_data_8v),

		.fao_we(blue_fao_we),
		.fao_wr_addr(blue_fao_wr_addr),
		.fao_wr_data(blue_fao_wr_data),
		.fao_rd_addr(blue_fao_rd_addr),
		.fao_rd_data(blue_fao_rd_data)
	);

	epi_compiler #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DUT_RED (
		.clk(clock_50),
		.pixel_valid_in(pixel_valid_in),
		.soc_in(soc_in),
		.eoc_in(eoc_in),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_in(pixel_in_red),

		.storage_we(red_storage_we),
		.storage_we_8v(red_storage_we_8v),
		.storage_wr_addr(red_storage_wr_addr),
		.storage_wr_addr_8v(red_storage_wr_addr_8v),
		.storage_wr_data(red_storage_wr_data),
		.storage_rd_addr(red_storage_rd_addr),
		.storage_rd_data(red_storage_rd_data),
		.storage_rd_data_8v(red_storage_rd_data_8v),
		.shared_banks_5_to_8_released(red_shared_banks_5_to_8_released),
		.shared_banks_5_to_8_epi_read_active(red_shared_banks_5_to_8_epi_read_active),

		.epi_valid_out(epi_valid_out_red),
		.epi_column_out(epi_column_out_red),
		.epi_column_idx_out(epi_column_idx_out_red),
		.epi_idx_out(epi_idx_out_red),
		.orientation_out(orientation_out_red)
	);

	epi_compiler #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DUT_GREEN (
		.clk(clock_50),
		.pixel_valid_in(pixel_valid_in),
		.soc_in(soc_in),
		.eoc_in(eoc_in),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_in(pixel_in_green),

		.storage_we(green_storage_we),
		.storage_we_8v(green_storage_we_8v),
		.storage_wr_addr(green_storage_wr_addr),
		.storage_wr_addr_8v(green_storage_wr_addr_8v),
		.storage_wr_data(green_storage_wr_data),
		.storage_rd_addr(green_storage_rd_addr),
		.storage_rd_data(green_storage_rd_data),
		.storage_rd_data_8v(green_storage_rd_data_8v),
		.shared_banks_5_to_8_released(green_shared_banks_5_to_8_released),
		.shared_banks_5_to_8_epi_read_active(green_shared_banks_5_to_8_epi_read_active),

		.epi_valid_out(epi_valid_out_green),
		.epi_column_out(epi_column_out_green),
		.epi_column_idx_out(epi_column_idx_out_green),
		.epi_idx_out(epi_idx_out_green),
		.orientation_out(orientation_out_green)
	);

	epi_compiler #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DUT_BLUE (
		.clk(clock_50),
		.pixel_valid_in(pixel_valid_in),
		.soc_in(soc_in),
		.eoc_in(eoc_in),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_in(pixel_in_blue),

		.storage_we(blue_storage_we),
		.storage_we_8v(blue_storage_we_8v),
		.storage_wr_addr(blue_storage_wr_addr),
		.storage_wr_addr_8v(blue_storage_wr_addr_8v),
		.storage_wr_data(blue_storage_wr_data),
		.storage_rd_addr(blue_storage_rd_addr),
		.storage_rd_data(blue_storage_rd_data),
		.storage_rd_data_8v(blue_storage_rd_data_8v),
		.shared_banks_5_to_8_released(blue_shared_banks_5_to_8_released),
		.shared_banks_5_to_8_epi_read_active(blue_shared_banks_5_to_8_epi_read_active),

		.epi_valid_out(epi_valid_out_blue),
		.epi_column_out(epi_column_out_blue),
		.epi_column_idx_out(epi_column_idx_out_blue),
		.epi_idx_out(epi_idx_out_blue),
		.orientation_out(orientation_out_blue)
	);

	// ------------------------------------------------------------------------
	// Tie off unused FAO side of shared storage
	// ------------------------------------------------------------------------
	always_comb begin
		for (int i = 0; i < 4; i++) begin
			red_fao_we[i]      = 1'b0;
			red_fao_wr_addr[i] = '0;
			red_fao_wr_data[i] = '0;
			red_fao_rd_addr[i] = '0;

			green_fao_we[i]      = 1'b0;
			green_fao_wr_addr[i] = '0;
			green_fao_wr_data[i] = '0;
			green_fao_rd_addr[i] = '0;

			blue_fao_we[i]      = 1'b0;
			blue_fao_wr_addr[i] = '0;
			blue_fao_wr_data[i] = '0;
			blue_fao_rd_addr[i] = '0;
		end
	end

	function automatic logic clkock_50_fix(input logic c);
		clkock_50_fix = c;
	endfunction

	// ------------------------------------------------------------------------
	// Output capture memories: RED
	// ------------------------------------------------------------------------
	logic                    out_valid_red_mem       [0:OUT_MAX_DEPTH-1];
	logic                    out_orientation_red_mem [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_col_idx_red_mem     [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_epi_idx_red_mem     [0:OUT_MAX_DEPTH-1];
	logic [14:0]             out_epi_col_red_mem     [0:8][0:OUT_MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Output capture memories: GREEN
	// ------------------------------------------------------------------------
	logic                    out_valid_green_mem       [0:OUT_MAX_DEPTH-1];
	logic                    out_orientation_green_mem [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_col_idx_green_mem     [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_epi_idx_green_mem     [0:OUT_MAX_DEPTH-1];
	logic [14:0]             out_epi_col_green_mem     [0:8][0:OUT_MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Output capture memories: BLUE
	// ------------------------------------------------------------------------
	logic                    out_valid_blue_mem       [0:OUT_MAX_DEPTH-1];
	logic                    out_orientation_blue_mem [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_col_idx_blue_mem     [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_epi_idx_blue_mem     [0:OUT_MAX_DEPTH-1];
	logic [14:0]             out_epi_col_blue_mem     [0:8][0:OUT_MAX_DEPTH-1];

	int out_idx_red;
	int out_idx_green;
	int out_idx_blue;

	int OUT_DEPTH_RED;
	int OUT_DEPTH_GREEN;
	int OUT_DEPTH_BLUE;

	// ------------------------------------------------------------------------
	// Helper: parse DEPTH=... from MIF header
	// ------------------------------------------------------------------------
	function automatic int read_depth_from_mif(string mif_path);
		int fd;
		string line;
		int d;
		int rc;

		d  = -1;
		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF to read depth: %s", mif_path);
		end

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			rc = $sscanf(line, "DEPTH=%d;", d);
			if (rc == 1) begin
				$fclose(fd);
				return d;
			end
		end

		$fclose(fd);
		$fatal(1, "ERROR: Could not find DEPTH=... in MIF header: %s", mif_path);
		return -1;
	endfunction

	// ------------------------------------------------------------------------
	// Load 1-bit MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_1(
		input string mif_path,
		input int depth,
		output logic mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 1'b0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 1'b0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Load 15-bit MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_15(
		input string mif_path,
		input int depth,
		output logic [14:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [14:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 15'd0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 15'd0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write 1-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_1_out(
		input string mif_path,
		input int depth,
		input logic mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=1;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %0b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write 7-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_7_out(
		input string mif_path,
		input int depth,
		input logic [IMAGE_DIM_BS-1:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=%0d;", IMAGE_DIM_BS);
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %07b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write 15-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_15_out(
		input string mif_path,
		input int depth,
		input logic [14:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=15;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %015b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Clear output memories
	// ------------------------------------------------------------------------
	task automatic clear_output_memories;
		begin
			out_idx_red   = 0;
			out_idx_green = 0;
			out_idx_blue  = 0;

			OUT_DEPTH_RED   = 0;
			OUT_DEPTH_GREEN = 0;
			OUT_DEPTH_BLUE  = 0;

			for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
				out_valid_red_mem[k]         = 1'b0;
				out_orientation_red_mem[k]   = 1'b0;
				out_col_idx_red_mem[k]       = '0;
				out_epi_idx_red_mem[k]       = '0;

				out_valid_green_mem[k]       = 1'b0;
				out_orientation_green_mem[k] = 1'b0;
				out_col_idx_green_mem[k]     = '0;
				out_epi_idx_green_mem[k]     = '0;

				out_valid_blue_mem[k]        = 1'b0;
				out_orientation_blue_mem[k]  = 1'b0;
				out_col_idx_blue_mem[k]      = '0;
				out_epi_idx_blue_mem[k]      = '0;
			end

			for (int c = 0; c < 9; c++) begin
				for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
					out_epi_col_red_mem[c][k]   = 15'd0;
					out_epi_col_green_mem[c][k] = 15'd0;
					out_epi_col_blue_mem[c][k]  = 15'd0;
				end
			end
		end
	endtask

	// ------------------------------------------------------------------------
	// Write one colour's outputs
	// ------------------------------------------------------------------------
	task automatic write_colour_outputs_red;
		begin
			write_mif_1_out ({OUT_DIR_RED,   "/SIM_EPI_VALID_OUT.mif"},       OUT_DEPTH_RED,   out_valid_red_mem);
			write_mif_1_out ({OUT_DIR_RED,   "/SIM_ORIENTATION_OUT.mif"},     OUT_DEPTH_RED,   out_orientation_red_mem);
			write_mif_7_out ({OUT_DIR_RED,   "/SIM_EPI_COLUMN_IDX_OUT.mif"},  OUT_DEPTH_RED,   out_col_idx_red_mem);
			write_mif_7_out ({OUT_DIR_RED,   "/SIM_EPI_IDX_OUT.mif"},         OUT_DEPTH_RED,   out_epi_idx_red_mem);

			for (int c = 0; c < 9; c++) begin
				write_mif_15_out({OUT_DIR_RED, "/SIM_EPI_COLUMN_OUT_", int_to_string(c), ".mif"}, OUT_DEPTH_RED, out_epi_col_red_mem[c]);
			end
		end
	endtask

	task automatic write_colour_outputs_green;
		begin
			write_mif_1_out ({OUT_DIR_GREEN,   "/SIM_EPI_VALID_OUT.mif"},       OUT_DEPTH_GREEN,   out_valid_green_mem);
			write_mif_1_out ({OUT_DIR_GREEN,   "/SIM_ORIENTATION_OUT.mif"},     OUT_DEPTH_GREEN,   out_orientation_green_mem);
			write_mif_7_out ({OUT_DIR_GREEN,   "/SIM_EPI_COLUMN_IDX_OUT.mif"},  OUT_DEPTH_GREEN,   out_col_idx_green_mem);
			write_mif_7_out ({OUT_DIR_GREEN,   "/SIM_EPI_IDX_OUT.mif"},         OUT_DEPTH_GREEN,   out_epi_idx_green_mem);

			for (int c = 0; c < 9; c++) begin
				write_mif_15_out({OUT_DIR_GREEN, "/SIM_EPI_COLUMN_OUT_", int_to_string(c), ".mif"}, OUT_DEPTH_GREEN, out_epi_col_green_mem[c]);
			end
		end
	endtask

	task automatic write_colour_outputs_blue;
		begin
			write_mif_1_out ({OUT_DIR_BLUE,   "/SIM_EPI_VALID_OUT.mif"},       OUT_DEPTH_BLUE,   out_valid_blue_mem);
			write_mif_1_out ({OUT_DIR_BLUE,   "/SIM_ORIENTATION_OUT.mif"},     OUT_DEPTH_BLUE,   out_orientation_blue_mem);
			write_mif_7_out ({OUT_DIR_BLUE,   "/SIM_EPI_COLUMN_IDX_OUT.mif"},  OUT_DEPTH_BLUE,   out_col_idx_blue_mem);
			write_mif_7_out ({OUT_DIR_BLUE,   "/SIM_EPI_IDX_OUT.mif"},         OUT_DEPTH_BLUE,   out_epi_idx_blue_mem);

			for (int c = 0; c < 9; c++) begin
				write_mif_15_out({OUT_DIR_BLUE, "/SIM_EPI_COLUMN_OUT_", int_to_string(c), ".mif"}, OUT_DEPTH_BLUE, out_epi_col_blue_mem[c]);
			end
		end
	endtask

	function automatic string int_to_string(input int v);
		string s;
		$sformat(s, "%0d", v);
		return s;
	endfunction

	// ------------------------------------------------------------------------
	// Capture ALL outputs every cycle so MIFs match waveform exactly
	// ------------------------------------------------------------------------
	always_ff @(posedge clock_50) begin
		if (out_idx_red < OUT_MAX_DEPTH) begin
			out_valid_red_mem[out_idx_red]        <= epi_valid_out_red;
			out_orientation_red_mem[out_idx_red]  <= orientation_out_red;
			out_col_idx_red_mem[out_idx_red]      <= epi_column_idx_out_red;
			out_epi_idx_red_mem[out_idx_red]      <= epi_idx_out_red;

			for (int c = 0; c < 9; c++) begin
				out_epi_col_red_mem[c][out_idx_red] <= epi_column_out_red[c];
			end

			out_idx_red <= out_idx_red + 1;
		end
		else begin
			$fatal(1, "ERROR: RED output capture overflow. Increase OUT_MAX_DEPTH.");
		end

		if (out_idx_green < OUT_MAX_DEPTH) begin
			out_valid_green_mem[out_idx_green]         <= epi_valid_out_green;
			out_orientation_green_mem[out_idx_green]   <= orientation_out_green;
			out_col_idx_green_mem[out_idx_green]       <= epi_column_idx_out_green;
			out_epi_idx_green_mem[out_idx_green]       <= epi_idx_out_green;

			for (int c = 0; c < 9; c++) begin
				out_epi_col_green_mem[c][out_idx_green] <= epi_column_out_green[c];
			end

			out_idx_green <= out_idx_green + 1;
		end
		else begin
			$fatal(1, "ERROR: GREEN output capture overflow. Increase OUT_MAX_DEPTH.");
		end

		if (out_idx_blue < OUT_MAX_DEPTH) begin
			out_valid_blue_mem[out_idx_blue]        <= epi_valid_out_blue;
			out_orientation_blue_mem[out_idx_blue]  <= orientation_out_blue;
			out_col_idx_blue_mem[out_idx_blue]      <= epi_column_idx_out_blue;
			out_epi_idx_blue_mem[out_idx_blue]      <= epi_idx_out_blue;

			for (int c = 0; c < 9; c++) begin
				out_epi_col_blue_mem[c][out_idx_blue] <= epi_column_out_blue[c];
			end

			out_idx_blue <= out_idx_blue + 1;
		end
		else begin
			$fatal(1, "ERROR: BLUE output capture overflow. Increase OUT_MAX_DEPTH.");
		end
	end

	// ------------------------------------------------------------------------
	// Main simulation
	// ------------------------------------------------------------------------
	int i;

	initial begin
		$dumpfile("dump_epic.vcd");
		$dumpvars(0, epi_compiler_tb);

		DEPTH = read_depth_from_mif(IN_PIXEL_RED_MIF);

		if (DEPTH <= 0) begin
			$fatal(1, "ERROR: DEPTH read as %0d.", DEPTH);
		end

		if (DEPTH > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH=%0d exceeds MAX_DEPTH=%0d.", DEPTH, MAX_DEPTH);
		end

		$display("INFO: Loading EPI compiler input MIFs from: %s", IN_DIR);

		load_mif_15(IN_PIXEL_RED_MIF,   DEPTH, pixel_red_mem);
		load_mif_15(IN_PIXEL_GREEN_MIF, DEPTH, pixel_green_mem);
		load_mif_15(IN_PIXEL_BLUE_MIF,  DEPTH, pixel_blue_mem);

		load_mif_1(IN_VALID_MIF, DEPTH, valid_mem);
		load_mif_1(IN_SOC_MIF,   DEPTH, soc_mem);
		load_mif_1(IN_EOC_MIF,   DEPTH, eoc_mem);
		load_mif_1(IN_SOLF_MIF,  DEPTH, solf_mem);
		load_mif_1(IN_EOLF_MIF,  DEPTH, eolf_mem);

		clear_output_memories();

		repeat (4) @(posedge clock_50);

		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_50);
			pixel_in_red   <= 15'd0;
			pixel_in_green <= 15'd0;
			pixel_in_blue  <= 15'd0;

			pixel_valid_in <= 1'b0;
			soc_in         <= 1'b0;
			eoc_in         <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;
		end

		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_50);

			pixel_in_red   <= pixel_red_mem[i];
			pixel_in_green <= pixel_green_mem[i];
			pixel_in_blue  <= pixel_blue_mem[i];

			pixel_valid_in <= valid_mem[i];
			soc_in         <= soc_mem[i];
			eoc_in         <= eoc_mem[i];
			solf_in        <= solf_mem[i];
			eolf_in        <= eolf_mem[i];
		end

		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_50);

			pixel_in_red   <= 15'd0;
			pixel_in_green <= 15'd0;
			pixel_in_blue  <= 15'd0;

			pixel_valid_in <= 1'b0;
			soc_in         <= 1'b0;
			eoc_in         <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;
		end

		@(posedge clock_50);

		OUT_DEPTH_RED   = out_idx_red;
		OUT_DEPTH_GREEN = out_idx_green;
		OUT_DEPTH_BLUE  = out_idx_blue;

		$display("INFO: Writing RED outputs   (depth=%0d) to %s", OUT_DEPTH_RED,   OUT_DIR_RED);
		$display("INFO: Writing GREEN outputs (depth=%0d) to %s", OUT_DEPTH_GREEN, OUT_DIR_GREEN);
		$display("INFO: Writing BLUE outputs  (depth=%0d) to %s", OUT_DEPTH_BLUE,  OUT_DIR_BLUE);

		write_colour_outputs_red();
		write_colour_outputs_green();
		write_colour_outputs_blue();

		$display("INFO: EPI compiler testbench finished.");
		$finish;
	end

endmodule