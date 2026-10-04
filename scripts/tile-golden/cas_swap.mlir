cuda_tile.module @m {
  entry @cas_swap(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>, %arg3: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %9 = constant <i32: 0> : tile<32xi32>
    %10 = cmpi greater_than_or_equal %7, %9, signed : tile<32xi32> -> tile<32xi1>
    %11, %12, %13 = get_tile_block_id : tile<i32>
    %14 = constant <i32: 32> : tile<i32>
    %15 = muli %11, %14 : tile<i32>
    %16 = reshape %15 : tile<i32> -> tile<1xi32>
    %17 = broadcast %16 : tile<1xi32> -> tile<32xi32>
    %18 = iota : tile<32xi32>
    %19 = addi %17, %18 : tile<32xi32>
    %20 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %21 = make_tensor_view %20, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %22 = make_partition_view %21 : partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %23, %24 = load_view_tko weak %22[%4] token=%8 : partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %25 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %26 = broadcast %25 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %27 = offset %26, %19 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %28, %29 = atomic_cas_tko relaxed device %27, %7, %23, %10 token=%24 : tile<32xptr<i32>>, tile<32xi32>, tile<32xi1> -> tile<32xi32>, token
    %30 = assume div_by<16>, %arg3 : tile<ptr<i32>>
    %31 = make_tensor_view %30, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %32 = make_partition_view %31 : partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %33, %34 = load_view_tko weak %32[%4] token=%29 : partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %35 = select %10, %28, %33 : tile<32xi1>, tile<32xi32>
    %36 = store_view_tko weak %35, %32[%4] token=%34 : tile<32xi32>, partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
