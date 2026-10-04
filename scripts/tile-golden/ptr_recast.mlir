cuda_tile.module @m {
  entry @ptr_recast(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %7 = broadcast %6 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = offset %7, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %13 = ptr_to_ptr %12 : tile<128xptr<i32>> -> tile<128xptr<f32>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<128xptr<f32>> -> tile<128xf32>, token
    %16 = ftof %14 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %17, %18, %19 = get_num_tile_blocks : tile<i32>
    %20 = constant <i32: 128> : tile<i32>
    %21 = muli %17, %20 : tile<i32>
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [%21], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %25, %26, %27 = get_tile_block_id : tile<i32>
    %28 = store_view_tko weak %16, %24[%25] token=%15 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
