cuda_tile.module @m {
  entry @dtype_i4(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %14 = pack %12 : tile<32xi32> -> tile<128xi8>
    %15 = unpack %14 : tile<128xi8> -> tile<256xi4>
    %16 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %17 = make_tensor_view %16, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %18 = make_partition_view %17 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %19, %20 = load_view_tko weak %18[%9] token=%13 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %21 = pack %19 : tile<32xi32> -> tile<128xi8>
    %22 = unpack %21 : tile<128xi8> -> tile<256xi4>
    %23 = exti %15 signed : tile<256xi4> -> tile<256xi32>
    %24 = exti %22 signed : tile<256xi4> -> tile<256xi32>
    %25 = exti %15 unsigned : tile<256xi4> -> tile<256xi32>
    %26 = iota : tile<256xi32>
    %27 = trunci %26 : tile<256xi32> -> tile<256xi1>
    %28 = constant <i32: 0> : tile<i32>
    %29 = addi %5, %28 : tile<i32>
    %30 = addi %23, %24 : tile<256xi32>
    %31 = trunci %30 : tile<256xi32> -> tile<256xi4>
    %32 = pack %31 : tile<256xi4> -> tile<128xi8>
    %33 = unpack %32 : tile<128xi8> -> tile<32xi32>
    %34 = reshape %29 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<32xi32>
    %36 = iota : tile<32xi32>
    %37 = addi %35, %36 : tile<32xi32>
    %38 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %39 = broadcast %38 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %40 = offset %39, %37 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %41 = store_ptr_tko weak %40, %33 token=%20 : tile<32xptr<i32>>, tile<32xi32> -> token
    %42 = constant <i32: 512> : tile<i32>
    %43 = addi %5, %42 : tile<i32>
    %44 = constant <i32: 1> : tile<256xi32>
    %45 = shri %23, %44 signed : tile<256xi32>
    %46 = trunci %45 : tile<256xi32> -> tile<256xi4>
    %47 = pack %46 : tile<256xi4> -> tile<128xi8>
    %48 = unpack %47 : tile<128xi8> -> tile<32xi32>
    %49 = reshape %43 : tile<i32> -> tile<1xi32>
    %50 = broadcast %49 : tile<1xi32> -> tile<32xi32>
    %51 = iota : tile<32xi32>
    %52 = addi %50, %51 : tile<32xi32>
    %53 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %54 = broadcast %53 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %55 = offset %54, %52 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %56 = store_ptr_tko weak %55, %48 token=%41 : tile<32xptr<i32>>, tile<32xi32> -> token
    %57 = constant <i32: 1024> : tile<i32>
    %58 = addi %5, %57 : tile<i32>
    %59 = constant <i32: 1> : tile<256xi32>
    %60 = shri %25, %59 signed : tile<256xi32>
    %61 = trunci %60 : tile<256xi32> -> tile<256xi4>
    %62 = pack %61 : tile<256xi4> -> tile<128xi8>
    %63 = unpack %62 : tile<128xi8> -> tile<32xi32>
    %64 = reshape %58 : tile<i32> -> tile<1xi32>
    %65 = broadcast %64 : tile<1xi32> -> tile<32xi32>
    %66 = iota : tile<32xi32>
    %67 = addi %65, %66 : tile<32xi32>
    %68 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %69 = broadcast %68 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %70 = offset %69, %67 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %71 = store_ptr_tko weak %70, %63 token=%56 : tile<32xptr<i32>>, tile<32xi32> -> token
    %72 = constant <i32: 1536> : tile<i32>
    %73 = addi %5, %72 : tile<i32>
    %74 = muli %23, %24 : tile<256xi32>
    %75 = trunci %74 : tile<256xi32> -> tile<256xi4>
    %76 = pack %75 : tile<256xi4> -> tile<128xi8>
    %77 = unpack %76 : tile<128xi8> -> tile<32xi32>
    %78 = reshape %73 : tile<i32> -> tile<1xi32>
    %79 = broadcast %78 : tile<1xi32> -> tile<32xi32>
    %80 = iota : tile<32xi32>
    %81 = addi %79, %80 : tile<32xi32>
    %82 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %83 = broadcast %82 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %84 = offset %83, %81 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %85 = store_ptr_tko weak %84, %77 token=%71 : tile<32xptr<i32>>, tile<32xi32> -> token
    %86 = constant <i32: 2048> : tile<i32>
    %87 = addi %5, %86 : tile<i32>
    %88 = select %27, %24, %23 : tile<256xi1>, tile<256xi32>
    %89 = trunci %88 : tile<256xi32> -> tile<256xi4>
    %90 = pack %89 : tile<256xi4> -> tile<128xi8>
    %91 = unpack %90 : tile<128xi8> -> tile<32xi32>
    %92 = reshape %87 : tile<i32> -> tile<1xi32>
    %93 = broadcast %92 : tile<1xi32> -> tile<32xi32>
    %94 = iota : tile<32xi32>
    %95 = addi %93, %94 : tile<32xi32>
    %96 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %97 = broadcast %96 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %98 = offset %97, %95 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %99 = store_ptr_tko weak %98, %91 token=%85 : tile<32xptr<i32>>, tile<32xi32> -> token
    return
  }
}
