cuda_tile.module @m {
  entry @attr_addf(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<128xi32>
    %9 = iota : tile<128xi32>
    %10 = addi %8, %9 : tile<128xi32>
    %11, %12, %13 = get_num_tile_blocks : tile<i32>
    %14 = constant <i32: 128> : tile<i32>
    %15 = muli %11, %14 : tile<i32>
    %16 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [%15], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %18 = make_partition_view %17 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %19, %20, %21 = get_tile_block_id : tile<i32>
    %22, %23 = load_view_tko weak %18[%19] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %24 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %26 = offset %25, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %27, %28 = atomic_rmw_tko relaxed device %26, addf, %22 token=%23 : tile<128xptr<f64>>, tile<128xf64> -> tile<128xf64>, token
    return
  }
}
