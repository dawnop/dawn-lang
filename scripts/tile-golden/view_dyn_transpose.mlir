cuda_tile.module @m {
  entry @view_dyn_transpose(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 0> : tile<i32>
    %3 = offset %arg0, %2 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %4, %5 = load_ptr_tko weak %3 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %6 = constant <i32: 1> : tile<i32>
    %7 = offset %arg0, %6 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %8, %9 = load_ptr_tko weak %7 token=%5 : tile<ptr<i32>> -> tile<i32>, token
    %10 = constant <i32: 2> : tile<i32>
    %11 = offset %arg0, %10 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %12, %13 = load_ptr_tko weak %11 token=%9 : tile<ptr<i32>> -> tile<i32>, token
    %14 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [%4, %8], strides = [%8, %12] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %16 = make_partition_view %15 : partition_view<tile=(32x32), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>
    %17 = offset %arg2, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %18 = make_tensor_view %17, shape = [%4, %8], strides = [%12, %4] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %19 = make_partition_view %18 : partition_view<tile=(32x32), tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>
    %20, %21, %22 = get_tile_block_id : tile<i32>
    %23, %24, %25 = get_tile_block_id : tile<i32>
    %26, %27 = load_view_tko weak %16[%20, %24] token=%13 : partition_view<tile=(32x32), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %28 = store_view_tko weak %26, %19[%20, %24] token=%27 : tile<32x32xf64>, partition_view<tile=(32x32), tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
