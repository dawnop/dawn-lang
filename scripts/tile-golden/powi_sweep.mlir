cuda_tile.module @m {
  entry @powi_sweep(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %15 = make_tensor_view %14, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %19 = fpowi %12, %17 : tile<128xf64>, tile<128xi32>
    %20, %21, %22 = get_num_tile_blocks : tile<i32>
    %23 = constant <i32: 256> : tile<i32>
    %24 = muli %20, %23 : tile<i32>
    %25 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %26 = make_tensor_view %25, shape = [%24], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %27 = make_partition_view %26 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %28 = constant <i32: 2> : tile<i32>
    %29 = muli %9, %28 : tile<i32>
    %30 = store_view_tko weak %19, %27[%29] token=%18 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %31 = trunci %17 : tile<128xi32> -> tile<128xi8>
    %32 = fpowi %12, %31 : tile<128xf64>, tile<128xi8>
    %33 = constant <i32: 2> : tile<i32>
    %34 = muli %9, %33 : tile<i32>
    %35 = constant <i32: 1> : tile<i32>
    %36 = addi %34, %35 : tile<i32>
    %37 = store_view_tko weak %32, %27[%36] token=%30 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
