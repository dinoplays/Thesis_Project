module top_level (
    input  wire         CLOCK_50,
    input  logic [23:0] PIXEL_BIT_DATA,
    input  wire         PIXEL_VALID_IN,
    input  wire         SOC_IN,
    input  wire         EOC_IN,
    input  wire         SOLF_IN,
    input  wire         EOLF_IN,

    output logic        SOLF_OUT,
    output logic        EOLF_OUT,
    output logic [6:0]  ROW_IDX_OUT,
    output logic [6:0]  COLUMN_IDX_OUT,
    output logic        PIXEL_VALID_OUT,
    output logic [9:0]  CONFIDENCE_PIXEL_BIT_DATA,
    output logic [15:0] DISPARITY_PIXEL_BIT_DATA
);

    parameter int unsigned IMAGE_DIM    = 128;
    parameter int unsigned IMAGE_DIM_BS = 7;

    logic [7:0] pixel_in_red;

    assign pixel_in_red = PIXEL_BIT_DATA[23:16];

    // ---------------------------------------------------------------------
    // Shared storage wires
    //
    // EPIC-side storage is 8-bit to save RAM.
    // FAO-side shared storage ports remain 15-bit for compatibility, but only lower bits are used.
    // ---------------------------------------------------------------------
    logic                                   epic_storage_we [0:11];
    logic                                   epic_storage_we_8v;
    logic [13:0]                            epic_storage_wr_addr [0:11];
    logic [13:0]                            epic_storage_wr_addr_8v;
    logic [7:0]                             epic_storage_wr_data;
    logic [13:0]                            epic_storage_rd_addr;
    logic [7:0]                             epic_storage_rd_data [0:11];
    logic [7:0]                             epic_storage_rd_data_8v;
    logic                                   epic_shared_banks_5_to_8_released;
    logic                                   epic_shared_banks_5_to_8_epi_read_active;

    logic                                   fao_shared_we [0:3];
    logic [13:0]                            fao_shared_wr_addr [0:3];
    logic [14:0]                            fao_shared_wr_data [0:3];
    logic [13:0]                            fao_shared_rd_addr [0:3];
    logic [14:0]                            fao_shared_rd_data [0:3];

    shared_frame_storage #(
        .IMAGE_DIM(IMAGE_DIM),
        .IMAGE_DIM_BS(IMAGE_DIM_BS)
    ) SHARED_RED (
        .clk(CLOCK_50),
        .takeover_banks_5_to_8(epic_shared_banks_5_to_8_released),
        .epi_read_banks_5_to_8_active(epic_shared_banks_5_to_8_epi_read_active),

        .epi_we(epic_storage_we),
        .epi_we_8v(epic_storage_we_8v),
        .epi_wr_addr(epic_storage_wr_addr),
        .epi_wr_addr_8v(epic_storage_wr_addr_8v),
        .epi_wr_data(epic_storage_wr_data),
        .epi_rd_addr(epic_storage_rd_addr),
        .epi_rd_data(epic_storage_rd_data),
        .epi_rd_data_8v(epic_storage_rd_data_8v),

        .fao_we(fao_shared_we),
        .fao_wr_addr(fao_shared_wr_addr),
        .fao_wr_data(fao_shared_wr_data),
        .fao_rd_addr(fao_shared_rd_addr),
        .fao_rd_data(fao_shared_rd_data)
    );

    // ---------------------------------------------------------------------
    // EPI compiler
    //
    // Low-pass filtering is no longer before EPIC. EPIC stores and emits
    // raw 8-bit red-channel samples.
    // ---------------------------------------------------------------------
    logic                    epi_valid_out_red       = 1'b0;
    logic                    epi_orientation_out_red = 1'b0;
    logic [7:0]              epi_column_out_red [0:8];
    logic [IMAGE_DIM_BS-1:0] epi_column_idx_out_red  = '0;
    logic [IMAGE_DIM_BS-1:0] epi_idx_out_red         = '0;

    epi_compiler #(
        .IMAGE_DIM(IMAGE_DIM),
        .IMAGE_DIM_BS(IMAGE_DIM_BS)
    ) EPIC_RED (
        .clk(CLOCK_50),
        .pixel_valid_in(PIXEL_VALID_IN),
        .soc_in(SOC_IN),
        .eoc_in(EOC_IN),
        .solf_in(SOLF_IN),
        .eolf_in(EOLF_IN),
        .pixel_in(pixel_in_red),

        .storage_we(epic_storage_we),
        .storage_we_8v(epic_storage_we_8v),
        .storage_wr_addr(epic_storage_wr_addr),
        .storage_wr_addr_8v(epic_storage_wr_addr_8v),
        .storage_wr_data(epic_storage_wr_data),
        .storage_rd_addr(epic_storage_rd_addr),
        .storage_rd_data(epic_storage_rd_data),
        .storage_rd_data_8v(epic_storage_rd_data_8v),
        .shared_banks_5_to_8_released(epic_shared_banks_5_to_8_released),
        .shared_banks_5_to_8_epi_read_active(epic_shared_banks_5_to_8_epi_read_active),

        .epi_valid_out(epi_valid_out_red),
        .epi_column_out(epi_column_out_red),
        .epi_column_idx_out(epi_column_idx_out_red),
        .epi_idx_out(epi_idx_out_red),
        .orientation_out(epi_orientation_out_red)
    );

    // ---------------------------------------------------------------------
    // Registered boundary between EPIC and CONF
    // ---------------------------------------------------------------------
    logic                    epi_valid_in       = 1'b0;
    logic [7:0]              epi_column_in [0:8];
    logic [IMAGE_DIM_BS-1:0] epi_column_idx_in  = '0;
    logic [IMAGE_DIM_BS-1:0] epi_idx_in         = '0;
    logic                    epi_orientation_in = 1'b0;

    always_ff @(posedge CLOCK_50) begin
        epi_valid_in       <= epi_valid_out_red;
        epi_column_in      <= epi_column_out_red;
        epi_column_idx_in  <= epi_column_idx_out_red;
        epi_idx_in         <= epi_idx_out_red;
        epi_orientation_in <= epi_orientation_out_red;
    end

    // ---------------------------------------------------------------------
    // Confidence + aligned derivative generation
    // ---------------------------------------------------------------------
    logic                            derivative_valid_out_red = 1'b0;
    logic signed [10:0]              angular_derivative_column_out_red [0:6];
    logic signed [10:0]              spatial_derivative_column_out_red [0:6];
    logic [IMAGE_DIM_BS-1:0]         derivative_row_idx_out_red = '0;
    logic [IMAGE_DIM_BS-1:0]         derivative_column_idx_out_red = '0;
    logic                            derivative_orientation_out_red = 1'b0;

    logic                            confidence_valid_out_red = 1'b0;
    logic [9:0]                      confidence_pixel_out_red = 10'd0;
    logic [IMAGE_DIM_BS-1:0]         confidence_row_idx_out_red = '0;
    logic [IMAGE_DIM_BS-1:0]         confidence_column_idx_out_red = '0;
    logic                            confidence_orientation_out_red = 1'b0;

    confidence_computer #(
        .IMAGE_DIM(IMAGE_DIM),
        .IMAGE_DIM_BS(IMAGE_DIM_BS)
    ) CONF_COMP_RED (
        .clk(CLOCK_50),
        .epi_valid_in(epi_valid_in),
        .epi_column_in(epi_column_in),
        .epi_column_idx_in(epi_column_idx_in),
        .epi_idx_in(epi_idx_in),
        .orientation_in(epi_orientation_in),

        .derivative_valid_out(derivative_valid_out_red),
        .angular_derivative_column_out(angular_derivative_column_out_red),
        .spatial_derivative_column_out(spatial_derivative_column_out_red),
        .derivative_row_idx_out(derivative_row_idx_out_red),
        .derivative_column_idx_out(derivative_column_idx_out_red),
        .derivative_orientation_out(derivative_orientation_out_red),

        .confidence_valid_out(confidence_valid_out_red),
        .confidence_pixel_out(confidence_pixel_out_red),
        .confidence_row_idx_out(confidence_row_idx_out_red),
        .confidence_column_idx_out(confidence_column_idx_out_red),
        .confidence_orientation_out(confidence_orientation_out_red)
    );

    // ---------------------------------------------------------------------
    // Disparity
    //
    // The aligned angular/spatial derivatives are generated once in the
    // confidence module and reused here.
    // ---------------------------------------------------------------------
    logic                            disparity_valid_out_red = 1'b0;
    logic                            disparity_orientation_out_red = 1'b0;
    logic [IMAGE_DIM_BS-1:0]         disparity_row_idx_out_red = '0;
    logic [IMAGE_DIM_BS-1:0]         disparity_column_idx_out_red = '0;
    logic signed [15:0]              disparity_pixel_out_red = 16'sd0;

    disparity_estimator #(
        .IMAGE_DIM(IMAGE_DIM),
        .IMAGE_DIM_BS(IMAGE_DIM_BS)
    ) DISP_EST_RED (
        .clk(CLOCK_50),

        .derivative_valid_in(derivative_valid_out_red),
        .angular_derivative_column_in(angular_derivative_column_out_red),
        .spatial_derivative_column_in(spatial_derivative_column_out_red),
        .derivative_row_idx_in(derivative_row_idx_out_red),
        .derivative_column_idx_in(derivative_column_idx_out_red),
        .derivative_orientation_in(derivative_orientation_out_red),

        .disparity_valid_out(disparity_valid_out_red),
        .disparity_pixel_out(disparity_pixel_out_red),
        .disparity_row_idx_out(disparity_row_idx_out_red),
        .disparity_column_idx_out(disparity_column_idx_out_red),
        .orientation_out(disparity_orientation_out_red)
    );

    // ---------------------------------------------------------------------
    // Fused aligned output
    // ---------------------------------------------------------------------
    logic                    solf_fao_out = 1'b0;
    logic                    eolf_fao_out = 1'b0;
    logic [IMAGE_DIM_BS-1:0] row_idx_fao_out = '0;
    logic [IMAGE_DIM_BS-1:0] column_idx_fao_out = '0;
    logic                    pixel_valid_fao_out = 1'b0;
    logic [9:0]              confidence_pixel_bit_data_fao_out = 10'd0;
    logic signed [15:0]      disparity_pixel_bit_data_fao_out = 16'sd0;

    fused_aligned_output #(
        .IMAGE_DIM(IMAGE_DIM),
        .IMAGE_DIM_BS(IMAGE_DIM_BS)
    ) FAO_RED (
        .clk(CLOCK_50),

        .confidence_valid_in(confidence_valid_out_red),
        .confidence_pixel_in(confidence_pixel_out_red),
        .confidence_row_idx_in(confidence_row_idx_out_red),
        .confidence_column_idx_in(confidence_column_idx_out_red),
        .confidence_orientation_in(confidence_orientation_out_red),

        .disparity_valid_in(disparity_valid_out_red),
        .disparity_pixel_in(disparity_pixel_out_red),
        .disparity_row_idx_in(disparity_row_idx_out_red),
        .disparity_column_idx_in(disparity_column_idx_out_red),
        .disparity_orientation_in(disparity_orientation_out_red),

        .shared_banks_available(epic_shared_banks_5_to_8_released),
        .shared_we(fao_shared_we),
        .shared_wr_addr(fao_shared_wr_addr),
        .shared_wr_data(fao_shared_wr_data),
        .shared_rd_addr(fao_shared_rd_addr),
        .shared_rd_data(fao_shared_rd_data),

        .solf_out(solf_fao_out),
        .eolf_out(eolf_fao_out),
        .pixel_valid_out(pixel_valid_fao_out),
        .row_idx_out(row_idx_fao_out),
        .column_idx_out(column_idx_fao_out),
        .confidence_pixel_bit_data(confidence_pixel_bit_data_fao_out),
        .weighted_disparity_pixel_bit_data(disparity_pixel_bit_data_fao_out)
    );

    // ---------------------------------------------------------------------
    // Final low-pass filter
    //
    // This is the only low-pass filter in the new pipeline. Confidence remains
    // 10-bit Q8.2 confidence and 16-bit Q8.8 disparity remain at the module output.
    // ---------------------------------------------------------------------

    bit_shift_low_pass_filter #(
        .IMAGE_DIM(IMAGE_DIM),
        .IMAGE_DIM_BS(IMAGE_DIM_BS)
    ) FINAL_LPF_RED (
        .clk(CLOCK_50),
        .solf_in(solf_fao_out),
        .eolf_in(eolf_fao_out),
        .pixel_valid_in(pixel_valid_fao_out),
        .row_idx_in(row_idx_fao_out),
        .column_idx_in(column_idx_fao_out),
        .confidence_in(confidence_pixel_bit_data_fao_out),
        .disparity_in(disparity_pixel_bit_data_fao_out),

        .solf_out(SOLF_OUT),
        .eolf_out(EOLF_OUT),
        .pixel_valid_out(PIXEL_VALID_OUT),
        .row_idx_out(ROW_IDX_OUT),
        .column_idx_out(COLUMN_IDX_OUT),
        .confidence_out(CONFIDENCE_PIXEL_BIT_DATA),
        .disparity_out(DISPARITY_PIXEL_BIT_DATA)
    );

endmodule