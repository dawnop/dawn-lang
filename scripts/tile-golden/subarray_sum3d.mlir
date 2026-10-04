cuda_tile.module @m {
  entry @subarray_sum3d(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<1024xi32>
    %4 = iota : tile<1024xi32>
    %5 = addi %3, %4 : tile<1024xi32>
    %6 = constant <i32: 256> : tile<1024xi32>
    %7 = divi %5, %6 signed : tile<1024xi32>
    %8 = constant <i32: 1> : tile<1024xi32>
    %9 = cmpi greater_than_or_equal %7, %8, signed : tile<1024xi32> -> tile<1024xi1>
    %10 = constant <i32: 3> : tile<1024xi32>
    %11 = cmpi less_than %7, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <i1: 0> : tile<1024xi1>
    %13 = select %9, %11, %12 : tile<1024xi1>, tile<1024xi1>
    %14 = constant <i32: 32> : tile<1024xi32>
    %15 = divi %5, %14 signed : tile<1024xi32>
    %16 = constant <i32: 8> : tile<1024xi32>
    %17 = remi %15, %16 signed : tile<1024xi32>
    %18 = constant <i32: 2> : tile<1024xi32>
    %19 = cmpi greater_than_or_equal %17, %18, signed : tile<1024xi32> -> tile<1024xi1>
    %20 = constant <i32: 7> : tile<1024xi32>
    %21 = cmpi less_than %17, %20, signed : tile<1024xi32> -> tile<1024xi1>
    %22 = constant <i1: 0> : tile<1024xi1>
    %23 = select %19, %21, %22 : tile<1024xi1>, tile<1024xi1>
    %24 = constant <i1: 0> : tile<1024xi1>
    %25 = select %13, %23, %24 : tile<1024xi1>, tile<1024xi1>
    %26 = remi %5, %14 signed : tile<1024xi32>
    %27 = constant <i32: 3> : tile<1024xi32>
    %28 = cmpi greater_than_or_equal %26, %27, signed : tile<1024xi32> -> tile<1024xi1>
    %29 = constant <i32: 30> : tile<1024xi32>
    %30 = cmpi less_than %26, %29, signed : tile<1024xi32> -> tile<1024xi1>
    %31 = constant <i1: 0> : tile<1024xi1>
    %32 = select %28, %30, %31 : tile<1024xi1>, tile<1024xi1>
    %33 = constant <i1: 0> : tile<1024xi1>
    %34 = select %25, %32, %33 : tile<1024xi1>, tile<1024xi1>
    %35 = constant <i32: 0> : tile<1024xi32>
    %36 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %37 = broadcast %36 : tile<1xptr<i32>> -> tile<1024xptr<i32>>
    %38 = offset %37, %5 : tile<1024xptr<i32>>, tile<1024xi32> -> tile<1024xptr<i32>>
    %39, %40 = load_ptr_tko weak %38, %34, %35 token=%0 : tile<1024xptr<i32>>, tile<1024xi1>, tile<1024xi32> -> tile<1024xi32>, token
    %41 = reduce %39 dim=0 identities=[0 : i32] : tile<1024xi32> -> tile<i32> (%42: tile<i32>, %43: tile<i32>) {
      %44 = addi %42, %43 : tile<i32>
      yield %44 : tile<i32>
    }
    %45 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %46 = make_tensor_view %45, shape = [1], strides = [1] : tensor_view<1xi32, strides=[1]>
    %47 = make_partition_view %46 : partition_view<tile=(1), padding_value = zero, tensor_view<1xi32, strides=[1]>, dim_map=[0]>
    %48, %49, %50 = get_tile_block_id : tile<i32>
    %51 = reshape %41 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<1xi32>
    %53 = store_view_tko weak %52, %47[%48] token=%40 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<1xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
