cuda_tile.module @m {
  entry @scatter_perm(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [256], strides = [1] : tensor_view<256xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %9 = constant <i32: 255> : tile<128xi32>
    %10 = andi %7, %9 : tile<128xi32>
    %11 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %12 = make_tensor_view %11, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %13 = make_partition_view %12 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %14, %15 = load_view_tko weak %13[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %16 = constant <i32: 0> : tile<128xi32>
    %17 = cmpi greater_than_or_equal %7, %16, signed : tile<128xi32> -> tile<128xi1>
    %18 = constant <i32: 256> : tile<128xi32>
    %19 = cmpi less_than %7, %18, signed : tile<128xi32> -> tile<128xi1>
    %20 = constant <i1: 0> : tile<128xi1>
    %21 = select %17, %19, %20 : tile<128xi1>, tile<128xi1>
    %22 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %23 = broadcast %22 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %24 = offset %23, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %25 = store_ptr_tko weak %24, %14, %21 token=%15 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
